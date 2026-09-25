package app

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"

	"github.com/jackc/pgx/v5"
)

func seedConversation(t *testing.T, a *App) string {
	t.Helper()
	id := ID()
	if _, e := a.DB.Exec(context.Background(), `INSERT INTO conversations(id,subject,create_idem) VALUES($1,'alice',$2)`, id, id); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() {
		a.DB.Exec(context.Background(), `DELETE FROM conversation_turns WHERE conversation=$1`, id)
		a.DB.Exec(context.Background(), `DELETE FROM conversations WHERE id=$1`, id)
	})
	return id
}
func assertConversationError(t *testing.T, e error, code string) {
	t.Helper()
	var api apiError
	if !errors.As(e, &api) || api.Code != code {
		t.Fatalf("want %s got %v", code, e)
	}
}
func TestDurableConversationConcurrencyAndRetry(t *testing.T) {
	a := testApp(t)
	ctx := context.Background()
	id := seedConversation(t, a)
	input := ConversationInput{Text: "你好", Mode: "auto", Timezone: "UTC"}
	var wg sync.WaitGroup
	var mu sync.Mutex
	var winners []savedTurn
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			turn, e := a.reserveConversationTurn(ctx, "alice", id, fmt.Sprint(i), input)
			mu.Lock()
			defer mu.Unlock()
			if e == nil {
				winners = append(winners, turn)
			} else {
				assertConversationError(t, e, "conversation_busy")
			}
		}(i)
	}
	wg.Wait()
	if len(winners) != 1 {
		t.Fatalf("winners %d", len(winners))
	}
	first := winners[0]
	if e := a.completeConversationTurn(ctx, "alice", id, first, map[string]any{"status": "answer", "answer": "你好"}, 200); e != nil {
		t.Fatal(e)
	}
	repeat, e := a.reserveConversationTurn(ctx, "alice", id, first.Idem, input)
	if e != nil || repeat.ID != first.ID || repeat.Status != "completed" || repeat.ResponseStatus != 200 {
		t.Fatalf("replay: %+v %v", repeat, e)
	}
	input.Text = "changed"
	_, e = a.reserveConversationTurn(ctx, "alice", id, first.Idem, input)
	assertConversationError(t, e, "idempotency_payload_conflict")
	_, e = a.reserveConversationTurn(ctx, "alice", id, "stale", input)
	assertConversationError(t, e, "conversation_changed")
	input.Revision = 1
	next, e := a.reserveConversationTurn(ctx, "alice", id, "next", input)
	if e != nil || len(next.History) != 2 {
		t.Fatalf("history: %+v %v", next, e)
	}
	a.failConversationTurn(ctx, next, E(502, "unavailable"))
	retry, e := a.reserveConversationTurn(ctx, "alice", id, "next", input)
	if e != nil || retry.ID != next.ID || retry.Fence == next.Fence {
		t.Fatalf("retry %+v %v", retry, e)
	}
	e = a.completeConversationTurn(ctx, "alice", id, next, map[string]any{"status": "answer", "answer": "stale"}, 200)
	assertConversationError(t, e, "conversation_changed")
	if e = a.completeConversationTurn(ctx, "alice", id, retry, map[string]any{"status": "answer", "answer": "new"}, 200); e != nil {
		t.Fatal(e)
	}
}
func TestDurableConversationLeaseAndFrozenHistory(t *testing.T) {
	a := testApp(t)
	ctx := context.Background()
	id := seedConversation(t, a)
	input := ConversationInput{Text: "hello", Mode: "auto", Timezone: "UTC"}
	first, e := a.reserveConversationTurn(ctx, "alice", id, "key", input)
	if e != nil {
		t.Fatal(e)
	}
	a.DB.Exec(ctx, `UPDATE conversation_turns SET lease_until=now()-interval '1 second' WHERE id=$1`, first.ID)
	a.DB.Exec(ctx, `UPDATE conversations SET summary='{"resolved_question":"a later changed anchor"}' WHERE id=$1`, id)
	retry, e := a.reserveConversationTurn(ctx, "alice", id, "key", input)
	if e != nil || retry.Fence == first.Fence || len(retry.History) != 0 || retry.HasQueryAnchor {
		t.Fatalf("frozen retry: %+v %v", retry, e)
	}
	e = a.completeConversationTurn(ctx, "alice", id, first, map[string]any{"status": "answer", "answer": "old"}, 200)
	assertConversationError(t, e, "conversation_changed")
	a.failConversationTurn(ctx, retry, E(502, "unavailable"))
	other, e := a.reserveConversationTurn(ctx, "alice", id, "other", input)
	if e != nil {
		t.Fatal(e)
	}
	if e = a.completeConversationTurn(ctx, "alice", id, other, map[string]any{"status": "answer", "answer": "ok"}, 200); e != nil {
		t.Fatal(e)
	}
	_, e = a.reserveConversationTurn(ctx, "alice", id, "key", input)
	assertConversationError(t, e, "conversation_changed")
}
func TestDurableConversationAccessAndSummary(t *testing.T) {
	a := testApp(t)
	ctx := context.Background()
	id := seedConversation(t, a)
	input := ConversationInput{Text: "2025年1月华东销售额", Mode: "auto", Timezone: "Asia/Shanghai"}
	_, e := a.reserveConversationTurn(ctx, "bob", id, "bad", input)
	if !errors.Is(e, pgx.ErrNoRows) {
		t.Fatalf("other owner: %v", e)
	}
	turn, e := a.reserveConversationTurn(ctx, "alice", id, "first", input)
	if e != nil {
		t.Fatal(e)
	}
	query := seedDataQuery(t, a)
	if e = a.completeConversationTurn(ctx, "alice", id, turn, map[string]any{"kind": "warehouse", "id": query, "question": input.Text}, 202); e != nil {
		t.Fatal(e)
	}
	var summary map[string]any
	var teams, datasets []string
	if e = a.DB.QueryRow(ctx, `SELECT summary,required_teams,required_datasets FROM conversations WHERE id=$1`, id).Scan(&summary, &teams, &datasets); e != nil {
		t.Fatal(e)
	}
	if summary["dataset_version"] != "teaching-2025q1-v1" || summary["contains_current_result"] != false || len(teams) != 1 || len(datasets) != 1 {
		t.Fatalf("summary: %v %v %v", summary, teams, datasets)
	}
	for i := 1; i <= 6; i++ {
		input.Revision = int64(i)
		input.Text = "你好"
		next, e := a.reserveConversationTurn(ctx, "alice", id, fmt.Sprint(i), input)
		if e != nil {
			t.Fatal(e)
		}
		if e = a.completeConversationTurn(ctx, "alice", id, next, map[string]any{"status": "answer", "answer": "你好"}, 200); e != nil {
			t.Fatal(e)
		}
	}
	input.Revision = 7
	input.Text = "换成华南"
	next, e := a.reserveConversationTurn(ctx, "alice", id, "followup", input)
	if e != nil {
		t.Fatal(e)
	}
	raw, _ := json.Marshal(next.History)
	if len(next.History) != 10 || !strings.Contains(string(raw), "2025年1月华东销售额") || strings.Contains(string(raw), "279159.5") {
		t.Fatalf("bounded anchored history: %s", raw)
	}
	// Revoke the source atomically in an isolated DB; restore even if assertion fails.
	t.Cleanup(func() { a.DB.Exec(ctx, `UPDATE query_datasets SET enabled=true WHERE id='commerce'`) })
	a.DB.Exec(ctx, `UPDATE query_datasets SET enabled=false WHERE id='commerce'`)
	e = a.completeConversationTurn(ctx, "alice", id, next, map[string]any{"status": "answer", "answer": "cached source"}, 200)
	if !errors.Is(e, pgx.ErrNoRows) {
		t.Fatalf("completion after revoke: %v", e)
	}
	_, e = a.reserveConversationTurn(ctx, "alice", id, "hidden", input)
	if !errors.Is(e, pgx.ErrNoRows) {
		t.Fatalf("admission after revoke: %v", e)
	}
	var visible bool
	e = a.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM conversations c WHERE c.id=$2 AND `+conversationScope+`)`, "alice", id).Scan(&visible)
	if e != nil || visible {
		t.Fatalf("read after revoke: %v %v", visible, e)
	}
}
func TestDurableConversationInput(t *testing.T) {
	for _, input := range []ConversationInput{{Text: ""}, {Text: "a", Mode: "shell"}, {Text: "a", Revision: -1}, {Text: "a", Timezone: "invalid"}} {
		if normalizeConversationInput(&input) == nil {
			t.Fatal("accepted invalid input")
		}
	}
	input := ConversationInput{Text: "  你好  "}
	if e := normalizeConversationInput(&input); e != nil || input.Text != "你好" || input.Mode != "auto" || input.Timezone != "UTC" {
		t.Fatalf("normalize: %+v %v", input, e)
	}
}

// A valid 2000-rune query may put its decisive constraint at the end. History
// must retain complete turns, dropping older pairs before dropping constraints.
func TestConversationHistoryPreservesTrailingConstraints(t *testing.T) {
	a := testApp(t)
	ctx := context.Background()
	id := seedConversation(t, a)
	question := strings.Repeat("背景", 995) + "，排除华东只查华南"
	summary := map[string]any{"resolved_question": question, "captured_at": "2026-09-25T00:00:00Z", "timezone": "UTC"}
	if _, e := a.DB.Exec(ctx, `UPDATE conversations SET summary=$2 WHERE id=$1`, id, summary); e != nil {
		t.Fatal(e)
	}
	for i := 0; i < 4; i++ {
		b := ConversationInput{Text: question, Mode: "auto", Timezone: "UTC", Revision: int64(i)}
		turn, e := a.reserveConversationTurn(ctx, "alice", id, fmt.Sprint(i), b)
		if e != nil {
			t.Fatal(e)
		}
		if e = a.completeConversationTurn(ctx, "alice", id, turn, map[string]any{"status": "answer", "answer": strings.Repeat("答", 2000)}, 200); e != nil {
			t.Fatal(e)
		}
	}
	b := ConversationInput{Text: "其他不变", Mode: "auto", Timezone: "UTC", Revision: 4}
	next, e := a.reserveConversationTurn(ctx, "alice", id, "followup", b)
	if e != nil {
		t.Fatal(e)
	}
	if e = (&UnifiedInput{Text: b.Text, History: next.History}).validateConversation(); e != nil {
		t.Fatal(e)
	}
	seenQuestion := 0
	for _, h := range next.History {
		if strings.Contains(h.Content, "背景") {
			if !strings.Contains(h.Content, "排除华东只查华南") {
				t.Fatal("decisive trailing constraint silently truncated")
			}
			seenQuestion++
		}
	}
	if seenQuestion < 2 {
		t.Fatal("missing both query anchor and recent user query")
	}
}

func TestContextResetSurvivesChatsAndDoesNotRemoveSourceACL(t *testing.T) {
	a := testApp(t)
	ctx := context.Background()
	id := seedConversation(t, a)
	seed := ConversationInput{Text: "2025年1月华东销售额", Mode: "auto", Timezone: "UTC"}
	first, e := a.reserveConversationTurn(ctx, "alice", id, "first", seed)
	if e != nil {
		t.Fatal(e)
	}
	if e = a.completeConversationTurn(ctx, "alice", id, first, map[string]any{"kind": "warehouse", "id": seedDataQuery(t, a), "question": seed.Text}, 202); e != nil {
		t.Fatal(e)
	}
	seed.Text = "忘掉之前查询，从零开始"
	seed.Revision = 1
	reset, e := a.reserveConversationTurn(ctx, "alice", id, "reset", seed)
	if e != nil {
		t.Fatal(e)
	}
	if e = a.completeConversationTurn(ctx, "alice", id, reset, map[string]any{"status": "answer", "answer": "不再沿用旧条件，历史保留。", "reset_context": true}, 200); e != nil {
		t.Fatal(e)
	}
	for i := 2; i < 8; i++ {
		seed.Revision = int64(i)
		seed.Text = "你好"
		next, e := a.reserveConversationTurn(ctx, "alice", id, fmt.Sprint(i), seed)
		if e != nil {
			t.Fatal(e)
		}
		if next.HasQueryAnchor {
			t.Fatal("reset retained a query anchor")
		}
		for _, h := range next.History {
			if strings.Contains(h.Content, "华东") {
				t.Fatal("reset resurrected old constraints")
			}
		}
		if e = a.completeConversationTurn(ctx, "alice", id, next, map[string]any{"status": "answer", "answer": "你好"}, 200); e != nil {
			t.Fatal(e)
		}
	}
	var anchor json.RawMessage
	var after int64
	var teams []string
	var count int
	if e = a.DB.QueryRow(ctx, `SELECT summary,context_after_seq,required_teams,(SELECT count(*) FROM conversation_turns WHERE conversation=$1) FROM conversations WHERE id=$1`, id).Scan(&anchor, &after, &teams, &count); e != nil {
		t.Fatal(e)
	}
	if string(anchor) != "{}" || after != reset.Seq || len(teams) != 1 || count != 8 {
		t.Fatalf("reset altered archive or ACL: %s %d %v %d", anchor, after, teams, count)
	}
	// A new task establishes a new anchor without resurrecting pre-reset turns.
	seed.Revision = 8
	seed.Text = "2026年2月全国订单数"
	fresh, e := a.reserveConversationTurn(ctx, "alice", id, "fresh", seed)
	if e != nil {
		t.Fatal(e)
	}
	if e = a.completeConversationTurn(ctx, "alice", id, fresh, map[string]any{"kind": "warehouse", "id": seedDataQuery(t, a), "question": seed.Text}, 202); e != nil {
		t.Fatal(e)
	}
	seed.Revision = 9
	seed.Text = "改成3月"
	follow, e := a.reserveConversationTurn(ctx, "alice", id, "next", seed)
	if e != nil {
		t.Fatal(e)
	}
	all, _ := json.Marshal(follow.History)
	if !follow.HasQueryAnchor || strings.Contains(string(all), "华东") || !strings.Contains(string(all), "2026年2月全国订单数") {
		t.Fatalf("new context: %s", all)
	}
}

func TestConversationFullStillAllowsRetry(t *testing.T) {
	a := testApp(t)
	ctx := context.Background()
	id := seedConversation(t, a)
	if _, e := a.DB.Exec(ctx, `INSERT INTO conversation_turns(id,conversation,idem,request_hash,base_revision,input,history,status,fence) SELECT gen_random_uuid(),$1,'seed-'||n,'fixture',0,'{"text":"fixture"}','[]','failed',gen_random_uuid() FROM generate_series(1,499) n`, id); e != nil {
		t.Fatal(e)
	}
	input := ConversationInput{Text: "最后一条", Mode: "auto", Timezone: "UTC"}
	last, e := a.reserveConversationTurn(ctx, "alice", id, "last", input)
	if e != nil {
		t.Fatal(e)
	}
	a.failConversationTurn(ctx, last, E(502, "unavailable"))
	_, e = a.reserveConversationTurn(ctx, "alice", id, "over-limit", input)
	assertConversationError(t, e, "conversation_full")
	retry, e := a.reserveConversationTurn(ctx, "alice", id, "last", input)
	if e != nil || retry.ID != last.ID || retry.Fence == last.Fence {
		t.Fatalf("full conversation retry: %+v %v", retry, e)
	}
	if e = a.completeConversationTurn(ctx, "alice", id, retry, map[string]any{"status": "answer", "answer": "已恢复"}, 200); e != nil {
		t.Fatal(e)
	}
	var count int
	a.DB.QueryRow(ctx, `SELECT count(*) FROM conversation_turns WHERE conversation=$1`, id).Scan(&count)
	if count != 500 {
		t.Fatalf("retry created extra turn: %d", count)
	}
}
