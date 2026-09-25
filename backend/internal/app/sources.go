package app

import (
	"context"
	"crypto/subtle"
	"github.com/jackc/pgx/v5"
	"net/http"
	"regexp"
)

func (a *App) sourceChange(w http.ResponseWriter, r *http.Request) error {
	if r.Header.Get("X-Protocol-Version") != "1" || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-Source-Key")), []byte(env("SOURCE_NOTIFY_KEY", "local-source-key"))) != 1 {
		return E(401, "invalid_source_identity")
	}
	var b struct {
		Service string `json:"service"`
		Delete  bool   `json:"delete"`
	}
	if e := decode(r, &b); e != nil {
		return e
	}
	e := a.transaction(r.Context(), func(tx pgx.Tx) error { return a.invalidateSource(r.Context(), tx, b.Service, b.Delete) })
	if e == nil {
		JSON(w, 200, map[string]string{"status": "invalidated"})
	}
	return e
}
func (a *App) invalidateSource(ctx context.Context, tx pgx.Tx, service string, remove bool) error {
	kind := "modified"
	if remove {
		kind = "deleted"
	}
	var version int64
	if e := tx.QueryRow(ctx, "update services set watermark=watermark+1 where id=$1 returning watermark", service).Scan(&version); e != nil {
		return e
	}
	_, e := tx.Exec(ctx, "insert into source_changes(service,watermark,kind) values($1,$2,$3)", service, version, kind)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, "update actions set state='invalidated' where investigation in (select id from investigations where service=$1) and state in ('draft','approved','rejected')", service)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, "update memories set status='expired' where service=$1 and status<>'revoked'", service)
	if e != nil {
		return e
	}
	if remove {
		_, e = tx.Exec(ctx, "update investigations set report=null,manifest=null where service=$1", service)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, "update actions set body='[source content removed]',result=case when result is null then null else result-'body' end where investigation in (select id from investigations where service=$1)", service)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, "update events set payload=jsonb_build_object('content_removed',true) where investigation in (select id from investigations where service=$1)", service)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, "update memories set content='',status='revoked' where service=$1", service)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, "update badcases set manifest=null where investigation in (select id from investigations where service=$1)", service)
		if e != nil {
			return e
		}
	}
	// Notify already-open workbenches; hiding content only on the next GET is insufficient.
	_, e = tx.Exec(ctx, "with changed as (update investigations set seq=seq+1 where service=$1 returning id,seq) insert into events(investigation,seq,kind,payload) select id,seq,'source_invalidated',jsonb_build_object('content_removed',$2::boolean,'watermark',$3::bigint) from changed", service, remove, version)
	return e
}
func (a *App) configureService(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.isAdmin(r); e != nil {
		return e
	}
	var b struct {
		Repo    string `json:"repo"`
		Enabled bool   `json:"enabled"`
	}
	if e := decode(r, &b); e != nil {
		return e
	}
	if !regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`).MatchString(b.Repo) {
		return E(400, "invalid_repository")
	}
	e := a.transaction(r.Context(), func(tx pgx.Tx) error {
		_, e := tx.Exec(r.Context(), "update services set repo=$2,enabled=$3 where id=$1", r.PathValue("id"), b.Repo, b.Enabled)
		if e != nil {
			return e
		}
		return a.invalidateSource(r.Context(), tx, r.PathValue("id"), false)
	})
	if e == nil {
		JSON(w, 200, map[string]string{"status": "updated"})
	}
	return e
}
