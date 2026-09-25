package app

import (
	"bytes"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"io"
	"net/http"
	"strings"
	"time"
)

type LogQuery struct {
	Mode   string   `json:"mode"`
	Terms  []string `json:"terms"`
	Levels []string `json:"levels"`
}

func (q *LogQuery) validate() error {
	if q.Mode == "" {
		q.Mode = "anomalies"
	}
	if q.Terms == nil {
		q.Terms = []string{}
	}
	if q.Levels == nil {
		q.Levels = []string{}
	}
	if q.Mode != "anomalies" && q.Mode != "search" && q.Mode != "all" {
		return E(400, "invalid_query_mode")
	}
	if len(q.Terms) > 6 || len(q.Levels) > 12 {
		return E(400, "query_too_large")
	}
	for _, t := range q.Terms {
		if len(strings.TrimSpace(t)) == 0 || len(t) > 100 {
			return E(400, "invalid_query_term")
		}
	}
	allowed := map[string]bool{"ERROR": true, "FATAL": true, "SEVERE": true, "FAILURE": true, "WARN": true, "WARNING": true, "CRITICAL": true, "ALERT": true, "EMERG": true, "INFO": true, "DEBUG": true, "TRACE": true, "UNKNOWN": true}
	for _, l := range q.Levels {
		if !allowed[l] {
			return E(400, "invalid_query_level")
		}
	}
	return nil
}

type naturalInput struct {
	Text     string `json:"text"`
	Timezone string `json:"timezone"`
}
type serviceOption struct {
	ID         string   `json:"id"`
	Name       string   `json:"name"`
	Aliases    []string `json:"aliases"`
	From       *string  `json:"available_from"`
	To         *string  `json:"available_to"`
	Provenance string   `json:"provenance"`
}

func (a *App) natural(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	var b naturalInput
	if e = decode(r, &b); e != nil {
		return e
	}
	if len(b.Text) < 3 || len(b.Text) > 4000 {
		return E(400, "invalid_question")
	}
	if _, e = time.LoadLocation(b.Timezone); e != nil {
		return E(400, "invalid_timezone")
	}
	key := r.Header.Get("Idempotency-Key")
	if len(key) == 0 || len(key) > 128 {
		return E(400, "invalid_idempotency_key")
	}
	requestHash := Hash(struct {
		Kind  string
		Input naturalInput
	}{"natural-v1", b})
	var oldID, oldHash, team string
	e = a.DB.QueryRow(r.Context(), "select id,request_hash,team from investigations where subject=$1 and idem=$2", u, key).Scan(&oldID, &oldHash, &team)
	if e == nil {
		if oldHash != requestHash {
			return E(409, "idempotency_payload_conflict")
		}
		if e = a.member(r.Context(), a.DB, u, team, false); e != nil {
			return e
		}
		JSON(w, 202, map[string]string{"id": oldID, "status": "accepted", "kind": "investigation"})
		return nil
	}
	if e != pgx.ErrNoRows {
		return e
	}
	rows, e := a.DB.Query(r.Context(), "select s.id,s.name from services s join members m on s.team=m.team where m.subject=$1 and s.enabled order by s.id", u)
	if e != nil {
		return e
	}
	options := []serviceOption{}
	ids := []string{}
	for rows.Next() {
		var s serviceOption
		if e = rows.Scan(&s.ID, &s.Name); e != nil {
			rows.Close()
			return e
		}
		s.Aliases = []string{}
		s.Provenance = "local-demo"
		options = append(options, s)
		ids = append(ids, s.ID)
	}
	rows.Close()
	if e = rows.Err(); e != nil {
		return e
	}
	if len(options) == 0 {
		JSON(w, 200, map[string]string{"status": "clarification", "clarification": "当前账号没有可查询的服务。"})
		return nil
	}
	var profiles []serviceOption
	if e = a.internalJSON(r, env("SOURCE_URL", "http://demo:8090")+"/catalog", map[string]any{"services": ids}, &profiles, 10*time.Second); e != nil {
		return e
	}
	for i := range options {
		for _, p := range profiles {
			if options[i].ID == p.ID {
				options[i].Aliases = p.Aliases
				options[i].From = p.From
				options[i].To = p.To
				options[i].Provenance = p.Provenance
			}
		}
	}
	var plan struct {
		Model         json.RawMessage `json:"model"`
		Status        string          `json:"status"`
		Clarification string          `json:"clarification"`
		Service       string          `json:"service"`
		Start         time.Time       `json:"start"`
		End           time.Time       `json:"end"`
		Query         LogQuery        `json:"query"`
		Explanation   string          `json:"explanation"`
		Mode          string          `json:"mode"`
	}
	if e = a.internalJSON(r, env("CONTEXT_URL", "http://context:8091")+"/context/v1/interpret", map[string]any{"text": b.Text, "timezone": b.Timezone, "now": time.Now().UTC(), "services": options}, &plan, 30*time.Second); e != nil {
		return e
	}
	if plan.Status == "clarification" {
		JSON(w, 200, map[string]string{"status": "clarification", "clarification": plan.Clarification, "mode": plan.Mode})
		return nil
	}
	allowed := false
	for _, id := range ids {
		if id == plan.Service {
			allowed = true
		}
	}
	if !allowed || plan.Status != "ready" {
		return E(502, "invalid_planner_scope")
	}
	// createTask validates timestamps, query shape and CURRENT membership again.
	return a.createTask(w, r, u, Create{Service: plan.Service, Symptom: b.Text, Start: plan.Start, End: plan.End, Timezone: b.Timezone, Query: plan.Query, Interpretation: map[string]any{"mode": plan.Mode, "explanation": plan.Explanation, "model": plan.Model}}, requestHash)
}
func (a *App) internalJSON(r *http.Request, url string, body, out any, timeout time.Duration) error {
	raw, e := json.Marshal(body)
	if e != nil {
		return e
	}
	req, e := http.NewRequestWithContext(r.Context(), "POST", url, bytes.NewReader(raw))
	if e != nil {
		return e
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Worker-Key", a.InternalKey)
	req.Header.Set("X-Protocol-Version", "1")
	client := &http.Client{Timeout: timeout}
	response, e := client.Do(req)
	if e != nil {
		return E(502, "query_service_unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return E(502, "query_interpretation_unavailable")
	}
	if e = json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(out); e != nil {
		return E(502, "invalid_planner_response")
	}
	return nil
}
