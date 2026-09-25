package app

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5/pgxpool"
	"net/http/httptest"
	"os"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
)

func testApp(t *testing.T) *App {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL required for real PostgreSQL tests")
	}
	db, e := pgxpool.New(context.Background(), url)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(db.Close)
	return &App{DB: db, InternalKey: "test", Lease: 15, MaxActive: 10}
}
func seedJob(t *testing.T, a *App) string {
	t.Helper()
	id := ID()
	ctx := context.Background()
	_, e := a.DB.Exec(ctx, "insert into investigations(id,team,service,subject,symptom,start_at,end_at,timezone,status,idem,request_hash,source_version) values($1,'orders','svc-17','alice','test',now()-interval '1 hour',now(),'UTC','queued',$2,'test',1)", id, id)
	if e != nil {
		t.Fatal(e)
	}
	_, e = a.DB.Exec(ctx, "insert into jobs(id) values($1)", id)
	if e != nil {
		t.Fatal(e)
	}
	return id
}
func internalRequest(body any) *httptest.ResponseRecorder { return httptest.NewRecorder() }
func callClaim(a *App, owner string) (map[string]any, error) {
	b, _ := json.Marshal(map[string]string{"owner": owner})
	r := httptest.NewRequest("POST", "/internal/v1/claim", bytes.NewReader(b))
	r.Header.Set("X-Worker-Key", "test")
	r.Header.Set("X-Protocol-Version", "1")
	w := httptest.NewRecorder()
	e := a.claim(w, r)
	var v map[string]any
	if w.Code == 200 {
		_ = json.Unmarshal(w.Body.Bytes(), &v)
	}
	return v, e
}
func callCallback(a *App, id, op string, b Callback) error {
	raw, _ := json.Marshal(b)
	r := httptest.NewRequest("POST", "/internal/v1/tasks/"+id+"/"+op, bytes.NewReader(raw))
	r.SetPathValue("id", id)
	r.SetPathValue("operation", op)
	r.Header.Set("X-Worker-Key", "test")
	r.Header.Set("X-Protocol-Version", "1")
	return a.callback(httptest.NewRecorder(), r)
}
func TestQueueCapacityFencingAndGoroutineConvergence(t *testing.T) {
	a := testApp(t)
	ctx := context.Background()
	_, e := a.DB.Exec(ctx, "truncate events,approvals,actions,feedback,memories,badcases,jobs,investigations cascade")
	if e != nil {
		t.Fatal(e)
	}
	for i := 0; i < 100; i++ {
		seedJob(t, a)
	}
	before := runtime.NumGoroutine()
	var wg sync.WaitGroup
	var mu sync.Mutex
	claimed := []map[string]any{}
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			v, e := callClaim(a, ID())
			if e != nil {
				t.Error(e)
				return
			}
			if v != nil {
				mu.Lock()
				claimed = append(claimed, v)
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if len(claimed) != 10 {
		t.Fatalf("got %d active leases, want 10", len(claimed))
	}
	seen := map[string]bool{}
	for _, v := range claimed {
		id := v["id"].(string)
		if seen[id] {
			t.Fatal("duplicate lease")
		}
		seen[id] = true
	}
	old := claimed[0]
	id := old["id"].(string)
	b := Callback{Owner: old["owner"].(string), Generation: int(old["generation"].(float64))}
	if e := callCallback(a, id, "heartbeat", b); e != nil {
		t.Fatal(e)
	}
	_, e = a.DB.Exec(ctx, "update jobs set lease_until=now()-interval '1 second',available_at=now()-interval '1 day' where id=$1", id)
	if e != nil {
		t.Fatal(e)
	}
	fresh, e := callClaim(a, "replacement")
	if e != nil {
		t.Fatal(e)
	}
	if fresh["id"] != id || fresh["generation"].(float64) != 2 {
		t.Fatalf("wrong takeover %v", fresh)
	}
	if e := callCallback(a, id, "heartbeat", b); e == nil {
		t.Fatal("old generation accepted")
	}
	b = Callback{Owner: "replacement", Generation: 2, CallbackID: "completion-1", Status: "completed", Report: json.RawMessage(`{"evidence":[],"facts":[],"candidates":[]}`), Manifest: json.RawMessage(`{}`)}
	// A bounded multi-source recording legitimately exceeds the former 32 KiB cap.
	large, _ := json.Marshal(map[string]string{"snapshot": strings.Repeat("x", 48000)})
	b.Manifest = large
	oversized, _ := json.Marshal(map[string]string{"snapshot": strings.Repeat("x", 524288)})
	invalid := b
	invalid.Manifest = oversized
	if e := callCallback(a, id, "result", invalid); e == nil {
		t.Fatal("oversized recording accepted")
	}
	if e := callCallback(a, id, "result", b); e != nil {
		t.Fatal(e)
	}
	if e := callCallback(a, id, "result", b); e != nil {
		t.Fatal("duplicate completion should replay", e)
	}
	b.Status = "partial"
	if e := callCallback(a, id, "result", b); e == nil {
		t.Fatal("changed callback accepted")
	}
	next := claimed[1]
	cid := next["id"].(string)
	_, e = a.DB.Exec(ctx, "update jobs set state='cancelled',lease_until=null where id=$1", cid)
	if e != nil {
		t.Fatal(e)
	}
	if e := callCallback(a, cid, "authorize", Callback{Owner: next["owner"].(string), Generation: 1, Tool: "logs"}); e == nil {
		t.Fatal("cancelled tool allowed")
	}
	time.Sleep(300 * time.Millisecond)
	after := runtime.NumGoroutine()
	if after > before+8 {
		t.Fatalf("goroutines failed to converge before=%d after=%d", before, after)
	}
	t.Logf("100 concurrent claims: 10 leases; takeover fenced; duplicate callbacks replayed; goroutines %d -> %d", before, after)
}
func TestGroundingGuard(t *testing.T) {
	for _, raw := range []string{`{"evidence":[],"answer_evidence":["missing"]}`, `{"evidence":[],"facts":[{"evidence":["missing"]}]}`, `{"evidence":[],"candidates":[{"evidence":[]}]}`, `{"evidence":[{"id":"a"},{"id":"a"}]}`} {
		if validateReport(json.RawMessage(raw)) == nil {
			t.Error("ungrounded accepted", raw)
		}
	}
	if validateReport(json.RawMessage(`{"evidence":[{"id":"a"}],"facts":[{"evidence":["a"]}]}`)) != nil {
		t.Fatal("valid references rejected")
	}
}
