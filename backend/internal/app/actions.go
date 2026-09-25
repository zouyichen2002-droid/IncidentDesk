package app

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/jackc/pgx/v5"
	"io"
	"net/http"
	"strings"
	"time"
)

type Draft struct {
	Version int    `json:"version"`
	Title   string `json:"title"`
	Body    string `json:"body"`
}

func (a *App) draft(w http.ResponseWriter, r *http.Request) error {
	u, e := a.access(r)
	if e != nil {
		return e
	}
	var b Draft
	if e = decode(r, &b); e != nil {
		return e
	}
	if len(b.Title) < 3 || len(b.Title) > 200 || len(b.Body) < 3 || len(b.Body) > 20000 {
		return E(400, "invalid_draft")
	}
	id := r.PathValue("id")
	e = a.transaction(r.Context(), func(tx pgx.Tx) error {
		ctx := r.Context()
		var team, target, status string
		var report []byte
		var version, current int64
		if e := tx.QueryRow(ctx, "select i.team,s.repo,i.status,i.report,i.source_version,s.watermark from investigations i join services s on s.id=i.service where i.id=$1 for update of i", id).Scan(&team, &target, &status, &report, &version, &current); e != nil {
			return e
		}
		if e := a.member(ctx, tx, u, team, false); e != nil {
			return e
		}
		if status != "completed" && status != "partial" {
			return E(409, "report_not_ready")
		}
		if version != current {
			return E(409, "evidence_stale")
		}
		var av int
		var state string
		err := tx.QueryRow(ctx, "select version,state from actions where investigation=$1 for update", id).Scan(&av, &state)
		if err != nil && err != pgx.ErrNoRows {
			return err
		}
		if state == "executing" || state == "unknown" || state == "succeeded" {
			return E(409, "action_already_dispatched")
		}
		if b.Version != av {
			return E(409, "version_conflict")
		}
		aid := ID()
		digest := Hash([]string{target, b.Title, b.Body, Hash(json.RawMessage(report))})
		_, err = tx.Exec(ctx, "insert into actions(id,investigation,version,state,target,title,body,digest,evidence_hash,source_version,marker) values($1,$2,1,'draft',$3,$4,$5,$6,$7,$8,$9) on conflict(investigation) do update set version=actions.version+1,state='draft',title=excluded.title,body=excluded.body,digest=excluded.digest,evidence_hash=excluded.evidence_hash,source_version=excluded.source_version,approved_by=null,approved_digest=null,approved_version=null,updated_at=now()", aid, id, target, b.Title, b.Body, digest, Hash(json.RawMessage(report)), version, "incidentdesk:"+aid)
		if err != nil {
			return err
		}
		return event(ctx, tx, id, "draft_saved", map[string]any{"version": av + 1, "subject": u, "digest": digest})
	})
	if e != nil {
		return e
	}
	return a.get(w, r)
}
func (a *App) decide(w http.ResponseWriter, r *http.Request) error {
	u, e := a.access(r)
	if e != nil {
		return e
	}
	var b struct {
		Version int `json:"version"`
	}
	if e = decode(r, &b); e != nil {
		return e
	}
	decision := r.PathValue("decision")
	if decision != "approve" && decision != "reject" && decision != "reconcile" {
		return E(400, "invalid_decision")
	}
	id := r.PathValue("id")
	e = a.transaction(r.Context(), func(tx pgx.Tx) error {
		ctx := r.Context()
		var aid, team, state, digest, eh, status, target, configured string
		var version int
		var sv, cv int64
		if e := tx.QueryRow(ctx, "select a.id,i.team,a.state,a.version,a.digest,a.evidence_hash,i.status,a.source_version,s.watermark,a.target,s.repo from actions a join investigations i on i.id=a.investigation join services s on s.id=i.service where i.id=$1 for update of a,i", id).Scan(&aid, &team, &state, &version, &digest, &eh, &status, &sv, &cv, &target, &configured); e != nil {
			return e
		}
		if e := a.member(ctx, tx, u, team, true); e != nil {
			return e
		}
		if version != b.Version {
			return E(409, "version_conflict")
		}
		if decision == "reconcile" {
			if state != "unknown" {
				return E(409, "not_unknown")
			}
			_, e := tx.Exec(ctx, "update actions set updated_at=now()-interval '1 minute' where id=$1", aid)
			return e
		}
		if status == "cancelled" || sv != cv || target != configured {
			return E(409, "approval_scope_stale")
		}
		if decision == "approve" && (state == "approved" || state == "executing" || state == "unknown" || state == "succeeded") {
			return nil
		}
		if state != "draft" && state != "rejected" {
			return E(409, "invalid_action_state")
		}
		next := "rejected"
		if decision == "approve" {
			next = "approved"
		}
		_, e := tx.Exec(ctx, "insert into approvals(id,action,version,digest,evidence_hash,subject,decision) values($1,$2,$3,$4,$5,$6,$7)", ID(), aid, version, digest, eh, u, decision)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, "update actions set state=$2,approved_by=$3,approved_version=version,approved_digest=digest,updated_at=now() where id=$1", aid, next, u)
		if e != nil {
			return e
		}
		return event(ctx, tx, id, next, map[string]any{"action": aid, "version": version, "digest": digest, "subject": u})
	})
	if e != nil {
		return e
	}
	return a.get(w, r)
}

type actionRun struct {
	ID, Investigation, Target, Title, Body, Marker string
	Reconcile                                      bool
}

func (a *App) RunActions(ctx context.Context) {
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			a.actionStep(ctx)
		}
	}
}
func (a *App) actionStep(ctx context.Context) {
	var run *actionRun
	e := a.transaction(ctx, func(tx pgx.Tx) error {
		var id, inv, target, title, body, marker, state, subject, team, istate, digest, approved, initiator string
		var sv, cv int64
		var v, av int
		e := tx.QueryRow(ctx, "select a.id,a.investigation,a.target,a.title,a.body,a.marker,a.state,coalesce(a.approved_by,''),i.team,i.status,a.digest,coalesce(a.approved_digest,''),a.source_version,s.watermark,a.version,coalesce(a.approved_version,0),i.subject from actions a join investigations i on i.id=a.investigation join services s on s.id=i.service where (a.state='approved' or (a.state in ('executing','unknown') and a.updated_at<now()-interval '15 seconds')) order by a.updated_at for update of a,i skip locked limit 1").Scan(&id, &inv, &target, &title, &body, &marker, &state, &subject, &team, &istate, &digest, &approved, &sv, &cv, &v, &av, &initiator)
		if e == pgx.ErrNoRows {
			return nil
		}
		if e != nil {
			return e
		}
		reconcile := state != "approved"
		if !reconcile && (istate == "cancelled" || sv != cv || v != av || digest != approved || a.member(ctx, tx, subject, team, true) != nil || a.member(ctx, tx, initiator, team, false) != nil) {
			_, e = tx.Exec(ctx, "update actions set state='invalidated',updated_at=now() where id=$1", id)
			if e != nil {
				return e
			}
			return event(ctx, tx, inv, "approval_invalidated", map[string]string{"action": id})
		}
		var configured string
		if e = tx.QueryRow(ctx, "select s.repo from services s join investigations i on i.service=s.id where i.id=$1", inv).Scan(&configured); e != nil {
			return e
		}
		if !reconcile && configured != target {
			return E(409, "target_changed")
		}
		next := "executing"
		if reconcile {
			next = "unknown"
		}
		_, e = tx.Exec(ctx, "update actions set state=$2,updated_at=now() where id=$1", id, next)
		if e != nil {
			return e
		}
		run = &actionRun{id, inv, target, title, body, marker, reconcile}
		return event(ctx, tx, inv, next, map[string]string{"action": id})
	})
	if e != nil || run == nil {
		return
	}
	var result map[string]any
	if run.Reconcile {
		result, e = a.reconcile(ctx, run)
	} else {
		result, e = a.issue(ctx, run)
	}
	state := "succeeded"
	if e != nil || result == nil {
		state = "unknown"
		result = map[string]any{"message": "Outcome unknown; reconcile by marker. Automatic re-creation disabled.", "marker": run.Marker}
	}
	_ = a.transaction(ctx, func(tx pgx.Tx) error {
		b, _ := json.Marshal(result)
		_, e := tx.Exec(ctx, "update actions set state=$2,result=$3,updated_at=now() where id=$1", run.ID, state, b)
		if e != nil {
			return e
		}
		return event(ctx, tx, run.Investigation, "action_"+state, map[string]any{"action": run.ID, "result": result})
	})
}
func (a *App) github(ctx context.Context, method, path string, body any) (map[string]any, error) {
	var buf io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		buf = bytes.NewReader(b)
	}
	req, e := http.NewRequestWithContext(ctx, method, env("GITHUB_API_URL", "http://localhost:8090/github")+path, buf)
	if e != nil {
		return nil, e
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	if token := env("GITHUB_TOKEN", ""); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, e := a.HTTP.Do(req)
	if e != nil {
		return nil, e
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("github_status_%d", resp.StatusCode)
	}
	var raw any
	if e = json.NewDecoder(io.LimitReader(resp.Body, 2<<20)).Decode(&raw); e != nil {
		return nil, e
	}
	if arr, ok := raw.([]any); ok {
		return map[string]any{"items": arr}, nil
	}
	m, ok := raw.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("invalid_response")
	}
	return m, nil
}
func (a *App) issue(ctx context.Context, r *actionRun) (map[string]any, error) {
	out, e := a.github(ctx, "POST", "/repos/"+r.Target+"/issues", map[string]string{"title": r.Title, "body": r.Body + "\n\n<!-- " + r.Marker + " -->"})
	if e != nil {
		return nil, e
	}
	n, ok := out["number"].(float64)
	if !ok {
		return nil, fmt.Errorf("missing_number")
	}
	verified, e := a.github(ctx, "GET", fmt.Sprintf("/repos/%s/issues/%d", r.Target, int(n)), nil)
	if e != nil {
		return nil, e
	}
	body, _ := verified["body"].(string)
	if !strings.Contains(body, r.Marker) {
		return nil, fmt.Errorf("readback_mismatch")
	}
	return verified, nil
}
func (a *App) reconcile(ctx context.Context, r *actionRun) (map[string]any, error) {
	var match map[string]any
	for page := 1; page <= 5; page++ {
		v, e := a.github(ctx, "GET", fmt.Sprintf("/repos/%s/issues?state=all&per_page=100&page=%d", r.Target, page), nil)
		if e != nil {
			return nil, e
		}
		items, _ := v["items"].([]any)
		for _, item := range items {
			m, ok := item.(map[string]any)
			if !ok {
				continue
			}
			body, _ := m["body"].(string)
			if strings.Contains(body, "<!-- "+r.Marker+" -->") {
				if match != nil {
					return nil, fmt.Errorf("ambiguous_marker")
				}
				match = m
			}
		}
		if len(items) < 100 {
			break
		}
	}
	if match == nil {
		return nil, fmt.Errorf("not_found_keep_unknown")
	}
	n, ok := match["number"].(float64)
	if !ok {
		return nil, fmt.Errorf("invalid_number")
	}
	return a.github(ctx, "GET", fmt.Sprintf("/repos/%s/issues/%d", r.Target, int(n)), nil)
}
