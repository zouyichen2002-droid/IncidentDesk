package app

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/jackc/pgx/v5"
	"net/http"
	"strconv"
	"time"
)

type Callback struct {
	Records    []map[string]any `json:"records"`
	Owner      string           `json:"owner"`
	Generation int              `json:"generation"`
	CallbackID string           `json:"callback_id"`
	Kind       string           `json:"kind"`
	Payload    json.RawMessage  `json:"payload"`
	Status     string           `json:"status"`
	Report     json.RawMessage  `json:"report"`
	Manifest   json.RawMessage  `json:"manifest"`
	Tool       string           `json:"tool"`
}

func (a *App) claim(w http.ResponseWriter, r *http.Request) error {
	if e := a.internal(r); e != nil {
		return e
	}
	var b struct {
		Owner string `json:"owner"`
	}
	if e := decode(r, &b); e != nil {
		return e
	}
	if len(b.Owner) < 1 || len(b.Owner) > 128 {
		return E(400, "invalid_worker")
	}
	var result json.RawMessage
	e := a.transaction(r.Context(), func(tx pgx.Tx) error {
		ctx := r.Context()
		if _, e := tx.Exec(ctx, "select pg_advisory_xact_lock(7002)"); e != nil {
			return e
		}
		_, e := tx.Exec(ctx, "update investigations set status='failed' where id in (select id from jobs where state in ('queued','running') and attempts>=4 and (lease_until is null or lease_until<now()))")
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, "update jobs set state='failed',last_error='retry_limit' where state in ('queued','running') and attempts>=4 and (lease_until is null or lease_until<now())")
		if e != nil {
			return e
		}
		var active int
		if e = tx.QueryRow(ctx, "select count(*) from jobs where state='running' and lease_until>now()").Scan(&active); e != nil {
			return e
		}
		if active >= a.MaxActive {
			return nil
		}
		var id, subject, team string
		e = tx.QueryRow(ctx, "select j.id,i.subject,i.team from jobs j join investigations i on i.id=j.id where ((j.state='queued' and j.available_at<=now()) or (j.state='running' and j.lease_until<now())) and i.status in ('queued','running') order by j.available_at for update of j,i skip locked limit 1").Scan(&id, &subject, &team)
		if e == pgx.ErrNoRows {
			return nil
		}
		if e != nil {
			return e
		}
		if e = a.member(ctx, tx, subject, team, false); e != nil {
			_, e = tx.Exec(ctx, "update jobs set state='failed',last_error='permission_revoked' where id=$1", id)
			if e != nil {
				return e
			}
			_, e = tx.Exec(ctx, "update investigations set status='failed' where id=$1", id)
			return e
		}
		_, e = tx.Exec(ctx, "update jobs set state='running',owner=$2,generation=generation+1,attempts=attempts+1,lease_until=now()+make_interval(secs=>$3) where id=$1", id, b.Owner, a.Lease)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, "update investigations set status='running',source_version=(select watermark from services where id=investigations.service) where id=$1", id)
		if e != nil {
			return e
		}
		if e = event(ctx, tx, id, "claimed", map[string]string{"worker": b.Owner}); e != nil {
			return e
		}
		result, e = queryJSON(ctx, tx, "select jsonb_build_object('protocol_version',1,'id',i.id,'subject',i.subject,'team',i.team,'service',i.service,'symptom',i.symptom,'query',i.query,'start',i.start_at,'end',i.end_at,'source_version',i.source_version,'generation',j.generation,'attempt',j.attempts,'owner',j.owner,'lease_seconds',$2::int,'budget',jsonb_build_object('steps',12,'seconds',120,'output_bytes',262144,'model_calls',3,'tokens',12000)) from investigations i join jobs j on i.id=j.id where i.id=$1", id, a.Lease)
		return e
	})
	if e != nil {
		return e
	}
	if result == nil {
		w.WriteHeader(204)
	} else {
		JSON(w, 200, result)
	}
	return nil
}
func (a *App) fence(ctx context.Context, tx pgx.Tx, id string, b Callback) (string, error) {
	var owner, state, subject, team string
	var generation int
	var live bool
	e := tx.QueryRow(ctx, "select j.owner,j.generation,j.state,coalesce(j.lease_until>now(),false),i.subject,i.team from jobs j join investigations i on i.id=j.id where j.id=$1 for update of j,i", id).Scan(&owner, &generation, &state, &live, &subject, &team)
	if e != nil {
		return "", e
	}
	if owner != b.Owner || generation != b.Generation || state != "running" || !live {
		return "", E(409, "stale_execution")
	}
	if e = a.member(ctx, tx, subject, team, false); e != nil {
		return "", e
	}
	return subject, nil
}
func (a *App) callback(w http.ResponseWriter, r *http.Request) error {
	if e := a.internal(r); e != nil {
		return e
	}
	var b Callback
	if e := decode(r, &b); e != nil {
		return e
	}
	id := r.PathValue("id")
	op := r.PathValue("operation")
	var result any = map[string]string{"status": "ok"}
	e := a.transaction(r.Context(), func(tx pgx.Tx) error {
		ctx := r.Context()
		if op == "result" {
			var old, hash, owner string
			var gen int
			e := tx.QueryRow(ctx, "select coalesce(last_callback,''),coalesce(result_hash,''),coalesce(owner,''),generation from jobs where id=$1 for update", id).Scan(&old, &hash, &owner, &gen)
			if e != nil {
				return e
			}
			if old == b.CallbackID && old != "" && owner == b.Owner && gen == b.Generation {
				if hash != Hash(b) {
					return E(409, "callback_payload_conflict")
				}
				return nil
			}
		}
		if _, e := a.fence(ctx, tx, id, b); e != nil {
			return e
		}
		switch op {
		case "sandbox":
			return event(ctx, tx, id, "sandbox_requested", map[string]any{"records": len(b.Records)})
		case "heartbeat":
			_, e := tx.Exec(ctx, "update jobs set lease_until=now()+make_interval(secs=>$2) where id=$1", id, a.Lease)
			return e
		case "authorize":
			allowed := map[string]bool{"logs": true, "deployments": true, "git": true, "runbook": true, "cluster": true, "context": true, "memory": true, "sandbox": true}
			if !allowed[b.Tool] {
				return E(403, "tool_not_allowed")
			}
			v, e := queryJSON(ctx, tx, "select jsonb_build_object('subject',i.subject,'team',i.team,'service',i.service,'query',i.query,'start',i.start_at,'end',i.end_at,'watermark',s.watermark,'generation',$2::int) from investigations i join services s on s.id=i.service where i.id=$1 and s.enabled", id, b.Generation)
			if e != nil {
				return e
			}
			if b.Tool == "memory" {
				v, e = queryJSON(ctx, tx, "select jsonb_build_object('memories',coalesce(jsonb_agg(to_jsonb(m)),'[]')) from memories m join investigations i on i.service=m.service join services s on s.id=m.service where i.id=$1 and m.team=i.team and m.status='confirmed' and m.source_version=s.watermark and m.expires_at>now()", id)
				if e != nil {
					return e
				}
			}
			result = v
			return event(ctx, tx, id, "authorized", map[string]any{"tool": b.Tool, "generation": b.Generation})
		case "event":
			if len(b.Kind) < 1 || len(b.Kind) > 64 || len(b.Payload) > 32768 {
				return E(400, "invalid_event")
			}
			return event(ctx, tx, id, b.Kind, b.Payload)
		case "result":
			var fresh bool
			if e := tx.QueryRow(ctx, "select i.source_version=s.watermark from investigations i join services s on s.id=i.service where i.id=$1", id).Scan(&fresh); e != nil {
				return e
			}
			if !fresh {
				return E(409, "source_version_changed")
			}
			if b.CallbackID == "" || len(b.Report) > 262144 || len(b.Manifest) > 524288 {
				return E(400, "invalid_result")
			}
			if b.Status != "completed" && b.Status != "partial" && b.Status != "waiting_information" && b.Status != "failed" {
				return E(400, "invalid_status")
			}
			if e := validateReport(b.Report); e != nil {
				return e
			}
			_, e := tx.Exec(ctx, "update investigations set status=$2,report=$3,manifest=$4 where id=$1", id, b.Status, b.Report, b.Manifest)
			if e != nil {
				return e
			}
			_, e = tx.Exec(ctx, "update jobs set state='done',lease_until=null,last_callback=$2,result_hash=$3 where id=$1", id, b.CallbackID, Hash(b))
			if e != nil {
				return e
			}
			return event(ctx, tx, id, "result", map[string]any{"status": b.Status, "generation": b.Generation})
		case "failure":
			_, e := tx.Exec(ctx, "update jobs set state='queued',lease_until=null,available_at=now()+make_interval(secs=>least(30,attempts*2)),last_error=$2 where id=$1", id, b.Kind)
			if e != nil {
				return e
			}
			_, e = tx.Exec(ctx, "update investigations set status='queued' where id=$1", id)
			return e
		}
		return E(404, "unknown_operation")
	})
	if e == nil && op == "sandbox" {
		result, e = a.sandbox(r.Context(), b.Records)
	}
	if e == nil {
		JSON(w, 200, result)
	}
	return e
}
func validateReport(raw json.RawMessage) error {
	var b struct {
		AnswerEvidence []string `json:"answer_evidence"`
		Evidence       []struct {
			ID string `json:"id"`
		} `json:"evidence"`
		Facts []struct {
			Evidence []string `json:"evidence"`
		} `json:"facts"`
		Candidates []struct {
			Evidence []string `json:"evidence"`
		} `json:"candidates"`
	}
	if json.Unmarshal(raw, &b) != nil {
		return E(400, "invalid_report")
	}
	ids := map[string]bool{}
	for _, e := range b.Evidence {
		if e.ID == "" || ids[e.ID] {
			return E(400, "invalid_evidence_ids")
		}
		ids[e.ID] = true
	}
	refs := [][]string{}
	if len(b.AnswerEvidence) > 0 {
		refs = append(refs, b.AnswerEvidence)
	}
	for _, f := range b.Facts {
		refs = append(refs, f.Evidence)
	}
	for _, f := range b.Candidates {
		refs = append(refs, f.Evidence)
	}
	for _, r := range refs {
		if len(r) == 0 {
			return E(400, "ungrounded_claim")
		}
		for _, id := range r {
			if !ids[id] {
				return E(400, "unknown_evidence")
			}
		}
	}
	return nil
}
func (a *App) events(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.access(r); e != nil {
		return e
	}
	cursor := r.Header.Get("Last-Event-ID")
	if cursor == "" {
		cursor = r.URL.Query().Get("after")
	}
	n, parseErr := strconv.ParseInt(cursor, 10, 64)
	if (cursor != "" && parseErr != nil) || n < 0 {
		return E(400, "invalid_cursor")
	}
	if r.Header.Get("Accept") != "text/event-stream" {
		v, e := queryJSON(r.Context(), a.DB, "select coalesce(jsonb_agg(x),'[]') from (select seq,kind,payload,created_at from events where investigation=$1 and seq>$2 order by seq limit 200) x", r.PathValue("id"), n)
		if e == nil {
			JSON(w, 200, v)
		}
		return e
	}
	fl, ok := w.(http.Flusher)
	if !ok {
		return E(500, "stream_unavailable")
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(200)
	var latest, earliest int64
	_ = a.DB.QueryRow(r.Context(), "select seq,coalesce((select min(seq) from events where investigation=i.id),seq) from investigations i where id=$1", r.PathValue("id")).Scan(&latest, &earliest)
	if n > latest || (n > 0 && n < earliest-1) {
		data, _ := json.Marshal(map[string]any{"seq": latest, "kind": "snapshot", "payload": map[string]any{"reload": true}})
		fmt.Fprintf(w, "id: %d\nevent: snapshot\ndata: %s\n\n", latest, data)
		n = latest
		fl.Flush()
	}
	timer := time.NewTimer(25 * time.Second)
	defer timer.Stop()
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	for {
		if _, e := a.access(r); e != nil {
			fmt.Fprint(w, "event: revoked\ndata: {}\n\n")
			fl.Flush()
			return nil
		}
		rows, e := a.DB.Query(r.Context(), "select seq,kind,payload from events where investigation=$1 and seq>$2 order by seq limit 200", r.PathValue("id"), n)
		if e != nil {
			return nil
		}
		for rows.Next() {
			var seq int64
			var kind string
			var p []byte
			if rows.Scan(&seq, &kind, &p) != nil {
				continue
			}
			data, _ := json.Marshal(map[string]any{"seq": seq, "kind": kind, "payload": json.RawMessage(p)})
			fmt.Fprintf(w, "id: %d\ndata: %s\n\n", seq, data)
			n = seq
		}
		rows.Close()
		fmt.Fprint(w, ": heartbeat\n\n")
		fl.Flush()
		select {
		case <-r.Context().Done():
			return nil
		case <-timer.C:
			return nil
		case <-ticker.C:
		}
	}
}
