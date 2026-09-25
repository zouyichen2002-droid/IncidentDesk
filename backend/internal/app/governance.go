package app

import (
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"net/http"
	"time"
)

func (a *App) feedback(w http.ResponseWriter, r *http.Request) error {
	u, e := a.access(r)
	if e != nil {
		return e
	}
	var b struct {
		Helpful    bool   `json:"helpful"`
		Confirmed  bool   `json:"confirmed"`
		FinalCause string `json:"final_cause"`
	}
	if e = decode(r, &b); e != nil {
		return e
	}
	if len(b.FinalCause) > 4000 {
		return E(400, "feedback_too_large")
	}
	_, e = a.DB.Exec(r.Context(), "insert into feedback(id,investigation,subject,helpful,confirmed,final_cause) values($1,$2,$3,$4,$5,$6)", ID(), r.PathValue("id"), u, b.Helpful, b.Confirmed, b.FinalCause)
	if e == nil {
		JSON(w, 201, map[string]string{"status": "saved"})
	}
	return e
}
func (a *App) replay(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.access(r); e != nil {
		return e
	}
	var stale bool
	if e := a.DB.QueryRow(r.Context(), "select i.source_version<>s.watermark or i.report is null from investigations i join services s on s.id=i.service where i.id=$1", r.PathValue("id")).Scan(&stale); e != nil {
		return e
	}
	if stale {
		return E(410, "recording_unavailable")
	}
	v, e := queryJSON(r.Context(), a.DB, "select jsonb_build_object('mode','offline_no_writes','report',i.report,'manifest',i.manifest,'events',(select coalesce(jsonb_agg(to_jsonb(e) order by e.seq),'[]') from events e where e.investigation=i.id)) from investigations i where id=$1", r.PathValue("id"))
	if e == nil {
		JSON(w, 200, v)
	}
	return e
}
func (a *App) memory(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.access(r); e != nil {
		return e
	}
	var b struct {
		Content string `json:"content"`
	}
	if e := decode(r, &b); e != nil {
		return e
	}
	if len(b.Content) < 3 || len(b.Content) > 4000 {
		return E(400, "invalid_memory")
	}
	id := ID()
	_, e := a.DB.Exec(r.Context(), "insert into memories(id,investigation,service,team,content,source_version,expires_at) select $1,id,service,team,$3,source_version,now()+interval '30 days' from investigations where id=$2", id, r.PathValue("id"), b.Content)
	if e == nil {
		JSON(w, 201, map[string]string{"id": id, "status": "candidate"})
	}
	return e
}
func (a *App) memories(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	v, e := queryJSON(r.Context(), a.DB, "select coalesce(jsonb_agg(to_jsonb(m)),'[]') from memories m join members p on p.team=m.team join services s on s.id=m.service where p.subject=$1 and m.status='confirmed' and m.expires_at>now() and m.source_version=s.watermark and ($2='' or m.service=$2)", u, r.URL.Query().Get("service"))
	if e == nil {
		JSON(w, 200, v)
	}
	return e
}
func (a *App) reviewMemory(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	state := map[string]string{"confirm": "confirmed", "revoke": "revoked"}[r.PathValue("decision")]
	if state == "" {
		return E(400, "invalid_decision")
	}
	e = a.transaction(r.Context(), func(tx pgx.Tx) error {
		var team string
		var stale bool
		if e := tx.QueryRow(r.Context(), "select m.team,m.source_version<>s.watermark or m.expires_at<now() from memories m join services s on s.id=m.service where m.id=$1 for update of m", r.PathValue("id")).Scan(&team, &stale); e != nil {
			return e
		}
		if e := a.member(r.Context(), tx, u, team, true); e != nil {
			return e
		}
		if state == "confirmed" && stale {
			return E(409, "memory_stale")
		}
		_, e := tx.Exec(r.Context(), "update memories set status=$2,reviewer=$3 where id=$1", r.PathValue("id"), state, u)
		if e != nil {
			return e
		}
		if state == "revoked" {
			var service string
			if e := tx.QueryRow(r.Context(), "select service from memories where id=$1", r.PathValue("id")).Scan(&service); e != nil {
				return e
			}
			return a.invalidateSource(r.Context(), tx, service, false)
		}
		return nil
	})
	if e == nil {
		JSON(w, 200, map[string]string{"status": state})
	}
	return e
}
func (a *App) badcase(w http.ResponseWriter, r *http.Request) error {
	u, e := a.access(r)
	if e != nil {
		return e
	}
	var b struct {
		Category string `json:"category"`
		Label    string `json:"label"`
	}
	if e = decode(r, &b); e != nil {
		return e
	}
	allowed := map[string]bool{"mapping": true, "retrieval": true, "conflict": true, "inference": true, "authorization": true, "tool": true, "recovery": true}
	if !allowed[b.Category] || len(b.Label) > 4000 {
		return E(400, "invalid_category")
	}
	var team string
	if e = a.DB.QueryRow(r.Context(), "select team from investigations where id=$1", r.PathValue("id")).Scan(&team); e != nil {
		return e
	}
	state := "candidate"
	reviewer := ""
	if b.Label != "" {
		if e = a.member(r.Context(), a.DB, u, team, true); e != nil {
			return e
		}
		state = "reviewed"
		reviewer = u
	}
	id := ID()
	_, e = a.DB.Exec(r.Context(), "insert into badcases(id,investigation,category,label,reviewer,status,manifest) select $1,id,$3,$4,$5,$6,manifest from investigations where id=$2", id, r.PathValue("id"), b.Category, b.Label, reviewer, state)
	if e == nil {
		JSON(w, 201, map[string]string{"id": id, "status": state})
	}
	return e
}
func (a *App) isAdmin(r *http.Request) (string, error) {
	u, e := a.user(r)
	if e != nil {
		return "", e
	}
	var yes bool
	if e = a.DB.QueryRow(r.Context(), "select exists(select 1 from admins where subject=$1)", u).Scan(&yes); e != nil {
		return "", e
	}
	if !yes {
		return "", E(403, "admin_required")
	}
	return u, nil
}
func (a *App) admin(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.isAdmin(r); e != nil {
		return e
	}
	v, e := queryJSON(r.Context(), a.DB, "select jsonb_build_object('members',(select jsonb_agg(to_jsonb(m)) from members m),'services',(select jsonb_agg(to_jsonb(s)) from services s),'connections',jsonb_build_object('database','ready','github_mode',$1::text))", env("GITHUB_MODE", "stub"))
	if e == nil {
		JSON(w, 200, v)
	}
	return e
}
func (a *App) setMember(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.isAdmin(r); e != nil {
		return e
	}
	var b struct {
		Subject string `json:"subject"`
		Team    string `json:"team"`
		Role    string `json:"role"`
	}
	if e := decode(r, &b); e != nil {
		return e
	}
	if b.Subject == "" || (b.Team != "orders" && b.Team != "payments") {
		return E(400, "invalid_member")
	}
	if b.Role != "" && b.Role != "approver" && b.Role != "investigator" {
		return E(400, "invalid_role")
	}
	e := a.transaction(r.Context(), func(tx pgx.Tx) error {
		if b.Role == "" {
			_, e := tx.Exec(r.Context(), "delete from members where subject=$1 and team=$2", b.Subject, b.Team)
			return e
		}
		_, e := tx.Exec(r.Context(), "insert into members(subject,team,role) values($1,$2,$3) on conflict(subject,team) do update set role=excluded.role", b.Subject, b.Team, b.Role)
		return e
	})
	if e == nil {
		JSON(w, 200, map[string]string{"status": "updated"})
	}
	return e
}
func (a *App) invalidate(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.isAdmin(r); e != nil {
		return e
	}
	var b struct {
		Delete bool `json:"delete"`
	}
	if e := decode(r, &b); e != nil {
		return e
	}
	e := a.transaction(r.Context(), func(tx pgx.Tx) error { return a.invalidateSource(r.Context(), tx, r.PathValue("id"), b.Delete) })
	if e == nil {
		JSON(w, 200, map[string]any{"status": "invalidated", "at": time.Now().UTC()})
	}
	return e
}

var _ = json.Valid

func (a *App) badcases(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	v, e := queryJSON(r.Context(), a.DB, "select coalesce(jsonb_agg(to_jsonb(b)),'[]') from badcases b join investigations i on i.id=b.investigation join members m on m.team=i.team where m.subject=$1", u)
	if e == nil {
		JSON(w, 200, v)
	}
	return e
}
func (a *App) reviewBadcase(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	var b struct {
		Label string `json:"label"`
	}
	if e = decode(r, &b); e != nil {
		return e
	}
	if len(b.Label) < 3 || len(b.Label) > 4000 {
		return E(400, "invalid_label")
	}
	e = a.transaction(r.Context(), func(tx pgx.Tx) error {
		var team string
		if e := tx.QueryRow(r.Context(), "select i.team from badcases b join investigations i on i.id=b.investigation where b.id=$1 for update of b", r.PathValue("id")).Scan(&team); e != nil {
			return e
		}
		if e := a.member(r.Context(), tx, u, team, true); e != nil {
			return e
		}
		_, e := tx.Exec(r.Context(), "update badcases set label=$2,reviewer=$3,status='reviewed' where id=$1", r.PathValue("id"), b.Label, u)
		return e
	})
	if e == nil {
		JSON(w, 200, map[string]string{"status": "reviewed"})
	}
	return e
}
