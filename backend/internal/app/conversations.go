package app

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// Applied on list, read, admission, retry, and completion. A conversation which
// has used restricted sources is hidden in its entirety after access is revoked.
const conversationScope = `c.subject=$1
 AND NOT EXISTS (SELECT 1 FROM unnest(c.required_teams) t WHERE NOT EXISTS(SELECT 1 FROM members m WHERE m.subject=$1 AND m.team=t))
 AND NOT EXISTS (SELECT 1 FROM unnest(c.required_datasets) k WHERE NOT EXISTS(SELECT 1 FROM query_datasets d JOIN members m ON m.team=d.team WHERE d.id=k AND d.enabled AND m.subject=$1))`

type ConversationInput struct {
	Text     string `json:"text"`
	Timezone string `json:"timezone"`
	Mode     string `json:"mode"`
	Revision int64  `json:"revision"`
}
type savedTurn struct {
	HasQueryAnchor bool               `json:"-"`
	ID             string             `json:"id"`
	Seq            int64              `json:"seq"`
	Idem           string             `json:"idem"`
	BaseRevision   int64              `json:"base_revision"`
	Input          ConversationInput  `json:"input"`
	Status         string             `json:"status"`
	Response       json.RawMessage    `json:"response"`
	ResponseStatus int                `json:"-"`
	Error          *string            `json:"error"`
	CreatedAt      time.Time          `json:"created_at"`
	History        []ConversationTurn `json:"-"`
	Fence          string             `json:"-"`
}

func validConversationID(id string) bool {
	var value pgtype.UUID
	return value.Scan(id) == nil && value.Valid
}
func idemKey(r *http.Request) (string, error) {
	key := r.Header.Get("Idempotency-Key")
	if len(key) == 0 || len(key) > 128 {
		return "", E(400, "invalid_idempotency_key")
	}
	return key, nil
}
func (a *App) createConversation(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	key, e := idemKey(r)
	if e != nil {
		return e
	}
	var body struct{}
	if e = decode(r, &body); e != nil {
		return e
	}
	var id string
	e = a.DB.QueryRow(r.Context(), `INSERT INTO conversations(id,subject,create_idem) VALUES($1,$2,$3) ON CONFLICT(subject,create_idem) DO UPDATE SET create_idem=excluded.create_idem RETURNING id`, ID(), u, key).Scan(&id)
	if e != nil {
		return e
	}
	r.SetPathValue("id", id)
	return a.getConversation(w, r)
}
func (a *App) listConversations(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	offset := 0
	if value := r.URL.Query().Get("offset"); value != "" {
		offset, e = strconv.Atoi(value)
		if e != nil || offset < 0 || offset > 100000 {
			return E(400, "invalid_offset")
		}
	}
	v, e := queryJSON(r.Context(), a.DB, `SELECT coalesce(jsonb_agg(x ORDER BY x.updated_at DESC,x.id),'[]') FROM (SELECT c.id,c.title,c.revision,c.updated_at FROM conversations c WHERE `+conversationScope+` ORDER BY c.updated_at DESC,c.id LIMIT 50 OFFSET $2) x`, u, offset)
	if e != nil {
		return e
	}
	JSON(w, 200, v)
	return nil
}
func (a *App) getConversation(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	id := r.PathValue("id")
	if !validConversationID(id) {
		return E(400, "invalid_conversation_id")
	}
	before := int64(9223372036854775807)
	if value := r.URL.Query().Get("before"); value != "" {
		before, e = strconv.ParseInt(value, 10, 64)
		if e != nil || before < 1 {
			return E(400, "invalid_cursor")
		}
	}
	v, e := queryJSON(r.Context(), a.DB, `SELECT jsonb_build_object('id',c.id,'title',c.title,'revision',c.revision,'summary',c.summary,'updated_at',c.updated_at,
 'turns',(SELECT coalesce(jsonb_agg(x ORDER BY x.seq),'[]') FROM (SELECT id,seq,idem,base_revision,input,status,response,error,created_at,lease_until FROM conversation_turns WHERE conversation=c.id AND seq<$3 ORDER BY seq DESC LIMIT 50) x),
 'has_more',(SELECT count(*)>50 FROM conversation_turns WHERE conversation=c.id AND seq<$3)) FROM conversations c WHERE c.id=$2 AND `+conversationScope, u, id, before)
	if e != nil {
		return e
	}
	JSON(w, 200, v)
	return nil
}

func normalizeConversationInput(b *ConversationInput) error {
	b.Text = strings.TrimSpace(b.Text)
	if b.Revision < 0 {
		return E(400, "invalid_revision")
	}
	if b.Timezone == "" {
		b.Timezone = "UTC"
	}
	if _, e := time.LoadLocation(b.Timezone); e != nil {
		return E(400, "invalid_timezone")
	}
	if b.Mode == "" {
		b.Mode = "auto"
	}
	if b.Mode != "auto" && b.Mode != "warehouse" && b.Mode != "investigation" {
		return E(400, "invalid_query_mode")
	}
	return (&UnifiedInput{Text: b.Text}).validateConversation()
}

// Reserve a short database transaction, never a transaction spanning an LLM call.
// History is frozen with the turn so a retry uses exactly the same context.
func (a *App) reserveConversationTurn(ctx context.Context, u, id, key string, b ConversationInput) (savedTurn, error) {
	var turn savedTurn
	e := a.transaction(ctx, func(tx pgx.Tx) error {
		var revision int64
		var summary json.RawMessage
		if e := tx.QueryRow(ctx, `SELECT c.revision,c.summary FROM conversations c WHERE c.id=$2 AND `+conversationScope+` FOR UPDATE`, u, id).Scan(&revision, &summary); e != nil {
			return e
		}
		if _, e := tx.Exec(ctx, `UPDATE conversation_turns SET status='failed',error='conversation_interrupted',updated_at=now() WHERE conversation=$1 AND status='pending' AND lease_until<now()`, id); e != nil {
			return e
		}
		var hash string
		e := tx.QueryRow(ctx, `SELECT id,seq,request_hash,base_revision,input,history,status,response,coalesce(response_status,0),error,created_at,has_query_anchor FROM conversation_turns WHERE conversation=$1 AND idem=$2`, id, key).Scan(&turn.ID, &turn.Seq, &hash, &turn.BaseRevision, &turn.Input, &turn.History, &turn.Status, &turn.Response, &turn.ResponseStatus, &turn.Error, &turn.CreatedAt, &turn.HasQueryAnchor)
		if e == nil {
			if hash != Hash(b) {
				return E(409, "idempotency_payload_conflict")
			}
			if turn.Status == "completed" {
				return nil
			}
			if turn.Status == "pending" {
				return E(409, "conversation_busy")
			}
			if turn.BaseRevision != revision {
				return E(409, "conversation_changed")
			}
		} else if e != pgx.ErrNoRows {
			return e
		}
		if b.Revision != revision {
			return E(409, "conversation_changed")
		}
		var pending bool
		if e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM conversation_turns WHERE conversation=$1 AND status='pending')`, id).Scan(&pending); e != nil {
			return e
		}
		if pending {
			return E(409, "conversation_busy")
		}
		turn.Fence = ID()
		if turn.ID != "" {
			_, e = tx.Exec(ctx, `UPDATE conversation_turns SET status='pending',error=null,fence=$2,lease_until=now()+interval '180 seconds',updated_at=now() WHERE id=$1`, turn.ID, turn.Fence)
			turn.Status = "pending"
			return e
		}
		var count int
		if e = tx.QueryRow(ctx, `SELECT count(*) FROM conversation_turns WHERE conversation=$1`, id).Scan(&count); e != nil {
			return e
		}
		if count >= 500 {
			return E(400, "conversation_full")
		}
		history, e := conversationHistory(ctx, tx, id, summary)
		if e != nil {
			return e
		}
		turn.ID = ID()
		turn.Input = b
		turn.History = history
		var anchor map[string]any
		if json.Unmarshal(summary, &anchor) == nil {
			turn.HasQueryAnchor = str(anchor, "resolved_question") != ""
		}
		turn.BaseRevision = revision
		turn.Status = "pending"
		turn.Idem = key
		e = tx.QueryRow(ctx, `INSERT INTO conversation_turns(id,conversation,idem,request_hash,base_revision,input,history,status,fence,lease_until,has_query_anchor) VALUES($1,$2,$3,$4,$5,$6,$7,'pending',$8,now()+interval '180 seconds',$9) RETURNING seq,created_at`, turn.ID, id, key, Hash(b), revision, b, history, turn.Fence, turn.HasQueryAnchor).Scan(&turn.Seq, &turn.CreatedAt)
		return e
	})
	return turn, e
}

func conversationHistory(ctx context.Context, tx pgx.Tx, id string, summary json.RawMessage) ([]ConversationTurn, error) {
	var turns []savedTurn
	rows, e := tx.Query(ctx, `SELECT input,response,created_at FROM conversation_turns WHERE conversation=$1 AND status='completed' AND seq>(SELECT context_after_seq FROM conversations WHERE id=$1) ORDER BY seq DESC LIMIT 4`, id)
	if e != nil {
		return nil, e
	}
	for rows.Next() {
		var t savedTurn
		if e = rows.Scan(&t.Input, &t.Response, &t.CreatedAt); e != nil {
			rows.Close()
			return nil, e
		}
		turns = append(turns, t)
	}
	rows.Close()
	if e = rows.Err(); e != nil {
		return nil, e
	}
	history := []ConversationTurn{}
	var anchor struct {
		Question   string `json:"resolved_question"`
		CapturedAt string `json:"captured_at"`
		Timezone   string `json:"timezone"`
	}
	if json.Unmarshal(summary, &anchor) == nil && anchor.Question != "" {
		// Keep the full resolved question in its own message. Prefixing it with
		// metadata used to truncate trailing filters on valid 2000-rune inputs.
		history = append(history,
			ConversationTurn{Role: "assistant", Content: "历史查询上下文（仅理解追问，不是当前结果；新话题优先）。下一条是当时的完整查询问题。创建于" + anchor.CapturedAt + "，时区" + anchor.Timezone},
			ConversationTurn{Role: "assistant", Content: anchor.Question})
	}
	pairs := []ConversationTurn{}
	for i := len(turns) - 1; i >= 0; i-- {
		t := turns[i]
		pairs = append(pairs, ConversationTurn{Role: "user", Content: t.Input.Text})
		var response map[string]any
		if e = json.Unmarshal(t.Response, &response); e != nil {
			return nil, e
		}
		reply := conversationReply(response, t.CreatedAt, t.Input.Timezone)
		if len([]rune(reply)) > 2000 {
			// Tool questions already obey the 2000-rune contract; do not cut off
			// their filters merely to fit the explanatory wrapper.
			reply = str(response, "question")
		}
		pairs = append(pairs, ConversationTurn{Role: "assistant", Content: reply})
	}
	size := func(values []ConversationTurn) int {
		n := 0
		for _, v := range values {
			n += len([]rune(v.Content))
		}
		return n
	}
	for len(pairs) > 2 && size(history)+size(pairs) > 16000 {
		pairs = pairs[2:]
	}
	history = append(history, pairs...)
	return history, nil
}
func shortText(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}
func str(m map[string]any, k string) string { v, _ := m[k].(string); return v }
func conversationReply(m map[string]any, created time.Time, zone string) string {
	if str(m, "status") == "answer" {
		return str(m, "answer")
	}
	if str(m, "status") == "clarification" {
		return str(m, "clarification")
	}
	return "已提交查询：" + str(m, "question") + "。请求时间：" + created.Format(time.RFC3339) + "，时区" + zone + "；相对时间以当次日期为基准。此处只记录任务引用，业务数值需重新查询。"
}

type conversationWriter struct {
	bytes.Buffer
	code   int
	header http.Header
}

func (w *conversationWriter) Header() http.Header  { return w.header }
func (w *conversationWriter) WriteHeader(code int) { w.code = code }
func (w *conversationWriter) Write(p []byte) (int, error) {
	if w.code == 0 {
		w.code = 200
	}
	return w.Buffer.Write(p)
}

func (a *App) postConversationTurn(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	id := r.PathValue("id")
	if !validConversationID(id) {
		return E(400, "invalid_conversation_id")
	}
	key, e := idemKey(r)
	if e != nil {
		return e
	}
	var b ConversationInput
	if e = decode(r, &b); e != nil {
		return e
	}
	if e = normalizeConversationInput(&b); e != nil {
		return e
	}
	turn, e := a.reserveConversationTurn(r.Context(), u, id, key, b)
	if e != nil {
		return e
	}
	if turn.Status == "completed" {
		JSON(w, turn.ResponseStatus, turn.Response)
		return nil
	}
	input := UnifiedInput{Text: b.Text, Timezone: b.Timezone, Mode: b.Mode, History: turn.History, queryAnchor: &turn.HasQueryAnchor}
	// The turn UUID is the downstream idempotency key, including after process restart.
	sub := r.Clone(r.Context())
	sub.Header = r.Header.Clone()
	sub.Header.Set("Idempotency-Key", "conversation:"+turn.ID)
	sub.Body = io.NopCloser(bytes.NewReader(nil))
	captured := &conversationWriter{header: make(http.Header)}
	e = a.executeUnified(captured, sub, u, input)
	finish, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if e != nil {
		a.failConversationTurn(finish, turn, e)
		return e
	}
	var response map[string]any
	if e = json.Unmarshal(captured.Bytes(), &response); e != nil {
		a.failConversationTurn(finish, turn, e)
		return e
	}
	// Semantic reset decisions are durable, including when a tool was selected.
	var decision queryDecision
	if x := a.DB.QueryRow(finish, `SELECT decision FROM unified_requests WHERE subject=$1 AND idem=$2`, u, "conversation:"+turn.ID).Scan(&decision); x != nil {
		a.failConversationTurn(finish, turn, x)
		return x
	}
	if str(response, "kind") == "investigation" {
		response["question"] = decision.Question
	}
	if decision.ResetContext {
		response["reset_context"] = true
	}
	response["conversation_id"] = id
	response["turn_id"] = turn.ID
	response["revision"] = turn.BaseRevision + 1
	if e = a.completeConversationTurn(finish, u, id, turn, response, captured.code); e != nil {
		a.failConversationTurn(finish, turn, e)
		return e
	}
	JSON(w, captured.code, response)
	return nil
}
func (a *App) failConversationTurn(ctx context.Context, t savedTurn, err error) {
	code := "conversation_interrupted"
	var api apiError
	if errors.As(err, &api) {
		code = api.Code
	}
	_, _ = a.DB.Exec(ctx, `UPDATE conversation_turns SET status='failed',error=$3,updated_at=now() WHERE id=$1 AND fence=$2 AND status='pending'`, t.ID, t.Fence, code)
}
func (a *App) completeConversationTurn(ctx context.Context, u, id string, t savedTurn, response map[string]any, status int) error {
	return a.transaction(ctx, func(tx pgx.Tx) error {
		var revision int64
		if e := tx.QueryRow(ctx, `SELECT c.revision FROM conversations c WHERE c.id=$2 AND `+conversationScope+` FOR UPDATE`, u, id).Scan(&revision); e != nil {
			return e
		}
		if revision != t.BaseRevision {
			return E(409, "conversation_changed")
		}
		team, dataset, version := "", "", ""
		kind := str(response, "kind")
		if kind == "warehouse" {
			if e := tx.QueryRow(ctx, `SELECT d.team,d.id,d.version FROM data_queries q JOIN query_datasets d ON d.id=q.dataset JOIN members m ON m.team=d.team WHERE q.id=$1 AND q.subject=$2 AND m.subject=$2 AND d.enabled`, str(response, "id"), u).Scan(&team, &dataset, &version); e != nil {
				return e
			}
		} else if kind == "investigation" {
			if e := tx.QueryRow(ctx, `SELECT i.team FROM investigations i JOIN members m ON m.team=i.team WHERE i.id=$1 AND i.subject=$2 AND m.subject=$2`, str(response, "id"), u).Scan(&team); e != nil {
				return e
			}
		}
		reset, _ := response["reset_context"].(bool)
		var summary any
		if reset {
			summary = map[string]any{}
		}
		if kind == "warehouse" || kind == "investigation" {
			summary = map[string]any{"schema_version": 1, "kind": kind, "resolved_question": str(response, "question"), "task_id": str(response, "id"), "dataset_id": dataset, "dataset_version": version, "captured_at": t.CreatedAt.Format(time.RFC3339), "timezone": t.Input.Timezone, "contains_current_result": false}
		}
		command, e := tx.Exec(ctx, `UPDATE conversation_turns SET status='completed',response=$3,response_status=$4,error=null,updated_at=now() WHERE id=$1 AND fence=$2 AND status='pending'`, t.ID, t.Fence, response, status)
		if e != nil {
			return e
		}
		if command.RowsAffected() != 1 {
			return E(409, "conversation_changed")
		}
		_, e = tx.Exec(ctx, `UPDATE conversations SET revision=revision+1,updated_at=now(),title=CASE WHEN revision=0 THEN $2 ELSE title END,
    required_teams=CASE WHEN $3='' OR $3=ANY(required_teams) THEN required_teams ELSE array_append(required_teams,$3) END,
    required_datasets=CASE WHEN $4='' OR $4=ANY(required_datasets) THEN required_datasets ELSE array_append(required_datasets,$4) END,
    summary=coalesce($5::jsonb,summary),context_after_seq=CASE WHEN $6::boolean THEN $7::bigint ELSE context_after_seq END WHERE id=$1`, id, shortText(t.Input.Text, 60), team, dataset, summary, reset, t.Seq)
		return e
	})
}
