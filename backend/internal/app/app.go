package app

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"go.opentelemetry.io/otel/trace"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/coreos/go-oidc/v3/oidc"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
)

type App struct {
	DB          *pgxpool.Pool
	verifier    *oidc.IDTokenVerifier
	HTTP        *http.Client
	InternalKey string
	Lease       int
	MaxActive   int
	mux         *http.ServeMux
	Requests    *prometheus.CounterVec
	Latency     *prometheus.HistogramVec
}
type apiError struct {
	Status int
	Code   string
}

func (e apiError) Error() string      { return e.Code }
func E(status int, code string) error { return apiError{status, code} }
func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}
func ID() string {
	b := make([]byte, 16)
	if _, e := rand.Read(b); e != nil {
		panic(e)
	}
	b[6] = (b[6] & 15) | 64
	b[8] = (b[8] & 63) | 128
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[:4], b[4:6], b[6:8], b[8:10], b[10:])
}
func Hash(v any) string {
	b, _ := json.Marshal(v)
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func JSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func decode(r *http.Request, v any) error {
	d := json.NewDecoder(http.MaxBytesReader(nil, r.Body, 2<<20))
	d.DisallowUnknownFields()
	if err := d.Decode(v); err != nil {
		return E(400, "invalid_json")
	}
	return nil
}
func fail(w http.ResponseWriter, err error) {
	var a apiError
	if errors.As(err, &a) {
		JSON(w, a.Status, map[string]string{"error": a.Code})
		return
	}
	if errors.Is(err, pgx.ErrNoRows) {
		JSON(w, 404, map[string]string{"error": "not_found"})
		return
	}
	slog.Error("request_failed", "class", fmt.Sprintf("%T", err), "error", err.Error())
	JSON(w, 500, map[string]string{"error": "internal_error"})
}
func New(ctx context.Context) (*App, error) {
	cfg, err := pgxpool.ParseConfig(env("DATABASE_URL", "postgres://incident_api:local-api@localhost:55432/incidentdesk?search_path=business"))
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 12
	cfg.MinConns = 1
	cfg.MaxConnLifetime = 30 * time.Minute
	db, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	if err = db.Ping(ctx); err != nil {
		return nil, err
	}
	p, err := oidc.NewProvider(ctx, env("OIDC_ISSUER", "http://localhost:8090"))
	if err != nil {
		return nil, err
	}
	a := &App{DB: db, verifier: p.Verifier(&oidc.Config{ClientID: "incidentdesk"}), HTTP: &http.Client{Timeout: 8 * time.Second}, InternalKey: env("INTERNAL_KEY", "local-worker-key"), Lease: 15, MaxActive: 10, mux: http.NewServeMux()}
	a.Requests = prometheus.NewCounterVec(prometheus.CounterOpts{Name: "incident_http_requests_total", Help: "Requests by route and result"}, []string{"route", "code"})
	a.Latency = prometheus.NewHistogramVec(prometheus.HistogramOpts{Name: "incident_http_seconds", Help: "API duration", Buckets: prometheus.DefBuckets}, []string{"route"})
	reg := prometheus.NewRegistry()
	reg.MustRegister(a.Requests, a.Latency, prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "incident_queue_depth", Help: "Queued jobs"}, func() float64 {
		var n int
		_ = db.QueryRow(context.Background(), "select count(*) from jobs where state='queued'").Scan(&n)
		return float64(n)
	}), prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "incident_active_jobs", Help: "Current leases"}, func() float64 {
		var n int
		_ = db.QueryRow(context.Background(), "select count(*) from jobs where state='running' and lease_until>now()").Scan(&n)
		return float64(n)
	}))
	reg.MustRegister(prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "incident_db_acquired", Help: "Connections checked out from API pool"}, func() float64 { return float64(db.Stat().AcquiredConns()) }), prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "incident_expired_leases", Help: "Expired running leases"}, func() float64 {
		var n int
		_ = db.QueryRow(context.Background(), "select count(*) from jobs where state='running' and lease_until<now()").Scan(&n)
		return float64(n)
	}), prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "incident_unknown_actions", Help: "External write outcomes requiring reconciliation"}, func() float64 {
		var n int
		_ = db.QueryRow(context.Background(), "select count(*) from actions where state='unknown'").Scan(&n)
		return float64(n)
	}), prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "incident_oldest_queue_seconds", Help: "Age of oldest queued job"}, func() float64 {
		var age float64
		_ = db.QueryRow(context.Background(), "select coalesce(extract(epoch from now()-min(available_at)),0) from jobs where state='queued'").Scan(&age)
		return age
	}))
	a.mux.Handle("GET /metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{}))
	a.routes()
	return a, nil
}
func (a *App) Handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Request-ID", ID())
		start := time.Now()
		ctx, span := otel.Tracer("incidentdesk/api").Start(r.Context(), r.Method+" "+r.URL.Path)
		defer span.End()
		r = r.WithContext(ctx)
		a.mux.ServeHTTP(w, r)
		span.SetAttributes(attribute.String("investigation_id", r.PathValue("id")))
		route := r.Pattern
		if route == "" {
			route = "unmatched"
		}
		a.Latency.WithLabelValues(route).Observe(time.Since(start).Seconds())
		span.SetAttributes(attribute.String("http.route", route))
	})
}
func (a *App) user(r *http.Request) (string, error) {
	token := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if token == "" {
		return "", E(401, "login_required")
	}
	t, err := a.verifier.Verify(r.Context(), token)
	if err != nil {
		return "", E(401, "invalid_token")
	}
	var count int
	err = a.DB.QueryRow(r.Context(), "insert into rate_limits(subject,window_start,count) values($1,$2,1) on conflict(subject,window_start) do update set count=rate_limits.count+1 returning count", t.Subject, time.Now().Unix()).Scan(&count)
	if err != nil {
		return "", err
	}
	if count > 100 {
		return "", E(429, "rate_limit")
	}
	return t.Subject, nil
}
func (a *App) member(ctx context.Context, q interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}, subject, team string, approve bool) error {
	var role string
	if err := q.QueryRow(ctx, "select role from members where subject=$1 and team=$2", subject, team).Scan(&role); err != nil {
		return E(403, "team_forbidden")
	}
	if approve && role != "approver" {
		return E(403, "approval_role_required")
	}
	return nil
}
func (a *App) internal(r *http.Request) error {
	if r.Header.Get("X-Protocol-Version") != "1" {
		return E(409, "protocol_version")
	}
	if subtle.ConstantTimeCompare([]byte(r.Header.Get("X-Worker-Key")), []byte(a.InternalKey)) != 1 {
		return E(401, "invalid_service_identity")
	}
	return nil
}
func event(ctx context.Context, tx pgx.Tx, id, kind string, payload any) error {
	var seq int64
	if e := tx.QueryRow(ctx, "update investigations set seq=seq+1,updated_at=now() where id=$1 returning seq", id).Scan(&seq); e != nil {
		return e
	}
	b, _ := json.Marshal(payload)
	_, e := tx.Exec(ctx, "insert into events(investigation,seq,kind,payload) values($1,$2,$3,$4)", id, seq, kind, b)
	return e
}
func (a *App) transaction(ctx context.Context, f func(pgx.Tx) error) error {
	tx, e := a.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	if e = f(tx); e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func (a *App) route(pattern string, f func(http.ResponseWriter, *http.Request) error) {
	a.mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) {
		err := f(w, r)
		code := "ok"
		if err != nil {
			code = "error"
			fail(w, err)
		}
		a.Requests.WithLabelValues(pattern, code).Inc()
	})
}
func (a *App) routes() {
	a.route("GET /healthz", func(w http.ResponseWriter, r *http.Request) error {
		JSON(w, 200, map[string]string{"status": "alive"})
		return nil
	})
	a.route("GET /readyz", func(w http.ResponseWriter, r *http.Request) error {
		ctx, c := context.WithTimeout(r.Context(), time.Second)
		defer c()
		if e := a.DB.Ping(ctx); e != nil {
			return E(503, "database_unavailable")
		}
		JSON(w, 200, map[string]string{"status": "ready"})
		return nil
	})
	a.route("GET /api/v1/me", a.me)
	a.route("POST /api/v1/queries", a.unifiedQuery)
	a.route("GET /api/v1/queries", a.queryList)
	a.route("GET /api/v1/queries/{id}", a.queryDetail)
	a.route("POST /api/v1/conversations", a.createConversation)
	a.route("GET /api/v1/conversations", a.listConversations)
	a.route("GET /api/v1/conversations/{id}", a.getConversation)
	a.route("POST /api/v1/conversations/{id}/turns", a.postConversationTurn)
	a.route("GET /api/v1/datasets", a.queryCatalog)
	a.route("GET /api/v1/services", a.services)
	a.route("POST /api/v1/investigations", a.create)
	a.route("POST /api/v1/investigations/natural", a.natural)
	a.route("GET /api/v1/investigations", a.list)
	a.route("GET /api/v1/investigations/{id}", a.get)
	a.route("POST /api/v1/investigations/{id}/cancel", a.cancel)
	a.route("POST /api/v1/investigations/{id}/resume", a.resume)
	a.route("GET /api/v1/investigations/{id}/events", a.events)
	a.route("PUT /api/v1/investigations/{id}/action", a.draft)
	a.route("POST /api/v1/investigations/{id}/action/{decision}", a.decide)
	a.route("POST /api/v1/investigations/{id}/feedback", a.feedback)
	a.route("GET /api/v1/investigations/{id}/replay", a.replay)
	a.route("POST /api/v1/investigations/{id}/memory", a.memory)
	a.route("GET /api/v1/memories", a.memories)
	a.route("POST /api/v1/memories/{id}/{decision}", a.reviewMemory)
	a.route("POST /api/v1/investigations/{id}/badcase", a.badcase)
	a.route("GET /api/v1/admin", a.admin)
	a.route("GET /api/v1/badcases", a.badcases)
	a.route("POST /api/v1/badcases/{id}/review", a.reviewBadcase)
	a.route("PUT /api/v1/admin/members", a.setMember)
	a.route("POST /api/v1/admin/services/{id}/invalidate", a.invalidate)
	a.route("POST /internal/v1/claim", a.claim)
	a.route("POST /internal/v1/source-change", a.sourceChange)
	a.route("PUT /api/v1/admin/services/{id}", a.configureService)
	a.route("POST /internal/v1/tasks/{id}/{operation}", a.callback)
}
func queryJSON(ctx context.Context, q interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}, sql string, args ...any) (json.RawMessage, error) {
	var b []byte
	e := q.QueryRow(ctx, sql, args...).Scan(&b)
	return b, e
}
func (a *App) me(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	v, e := queryJSON(r.Context(), a.DB, "select jsonb_build_object('subject',$1::text,'memberships',coalesce((select jsonb_agg(jsonb_build_object('team',team,'role',role)) from members where subject=$1),'[]'),'admin',exists(select 1 from admins where subject=$1))", u)
	if e == nil {
		JSON(w, 200, v)
	}
	return e
}
func (a *App) services(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	v, e := queryJSON(r.Context(), a.DB, "select coalesce(jsonb_agg(to_jsonb(s)),'[]') from services s join members m on s.team=m.team where m.subject=$1 and s.enabled", u)
	if e == nil {
		JSON(w, 200, v)
	}
	return e
}

type Create struct {
	Service        string         `json:"service"`
	Symptom        string         `json:"symptom"`
	Start          time.Time      `json:"start"`
	End            time.Time      `json:"end"`
	Timezone       string         `json:"timezone"`
	Query          LogQuery       `json:"query"`
	Interpretation map[string]any `json:"-"`
}

func (a *App) create(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	var b Create
	if e = decode(r, &b); e != nil {
		return e
	}
	return a.createTask(w, r, u, b, Hash(b))
}

func (a *App) createTask(w http.ResponseWriter, r *http.Request, u string, b Create, requestHash string) error {
	if e := b.Query.validate(); e != nil {
		return e
	}
	var e error
	idem := r.Header.Get("Idempotency-Key")
	if len(idem) < 1 || len(idem) > 128 || len(b.Symptom) < 3 || len(b.Symptom) > 4000 || b.Start.IsZero() || b.End.Before(b.Start) || b.End.Sub(b.Start) > 7*24*time.Hour {
		return E(400, "invalid_scope")
	}
	if _, e = time.LoadLocation(b.Timezone); e != nil {
		return E(400, "invalid_timezone")
	}
	id := ID()
	e = a.transaction(r.Context(), func(tx pgx.Tx) error {
		_, e := tx.Exec(r.Context(), "select pg_advisory_xact_lock(7001)")
		if e != nil {
			return e
		}
		var oldID, h string
		e = tx.QueryRow(r.Context(), "select id,request_hash from investigations where subject=$1 and idem=$2", u, idem).Scan(&oldID, &h)
		if e == nil {
			if h != requestHash {
				return E(409, "idempotency_payload_conflict")
			}
			id = oldID
			return nil
		}
		var team string
		var version int64
		if e = tx.QueryRow(r.Context(), "select team,watermark from services where id=$1 and enabled", b.Service).Scan(&team, &version); e != nil {
			return e
		}
		if e = a.member(r.Context(), tx, u, team, false); e != nil {
			return e
		}
		var n int
		if e = tx.QueryRow(r.Context(), "select count(*) from investigations where team=$1 and status in ('queued','running')", team).Scan(&n); e != nil {
			return e
		}
		if n >= 200 {
			return E(429, "team_quota_exhausted")
		}
		_, e = tx.Exec(r.Context(), "insert into investigations(id,team,service,subject,symptom,start_at,end_at,timezone,status,idem,request_hash,source_version,trace_id,query) values($1,$2,$3,$4,$5,$6,$7,$8,'queued',$9,$10,$11,$12,$13)", id, team, b.Service, u, b.Symptom, b.Start, b.End, b.Timezone, idem, requestHash, version, trace.SpanFromContext(r.Context()).SpanContext().TraceID().String(), b.Query)
		if e != nil {
			return e
		}
		if _, e = tx.Exec(r.Context(), "insert into jobs(id) values($1)", id); e != nil {
			return e
		}
		return event(r.Context(), tx, id, "queued", map[string]any{"request_id": w.Header().Get("X-Request-ID"), "interpretation": b.Interpretation})
	})
	if e != nil {
		return e
	}
	JSON(w, 202, map[string]string{"id": id, "status": "accepted", "kind": "investigation"})
	return nil
}
func (a *App) access(r *http.Request) (string, error) {
	u, e := a.user(r)
	if e != nil {
		return "", e
	}
	var team string
	if e = a.DB.QueryRow(r.Context(), "select team from investigations where id=$1", r.PathValue("id")).Scan(&team); e != nil {
		return "", e
	}
	return u, a.member(r.Context(), a.DB, u, team, false)
}
func (a *App) list(w http.ResponseWriter, r *http.Request) error {
	u, e := a.user(r)
	if e != nil {
		return e
	}
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	if offset < 0 || offset > 100000 {
		return E(400, "invalid_offset")
	}
	v, e := queryJSON(r.Context(), a.DB, "select coalesce(jsonb_agg(x),'[]') from (select i.id,i.service,i.symptom,i.status,i.created_at,i.updated_at,i.seq from investigations i join members m on m.team=i.team where m.subject=$1 order by i.created_at desc,i.id limit 50 offset $2) x", u, offset)
	if e == nil {
		JSON(w, 200, v)
	}
	return e
}
func (a *App) get(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.access(r); e != nil {
		return e
	}
	v, e := queryJSON(r.Context(), a.DB, "select to_jsonb(i)||jsonb_build_object('report',case when i.source_version=s.watermark then i.report else null end,'manifest',case when i.source_version=s.watermark then i.manifest else null end,'action',(select to_jsonb(a) from actions a where a.investigation=i.id),'evidence_stale',i.source_version<>s.watermark) from investigations i join services s on s.id=i.service where i.id=$1", r.PathValue("id"))
	if e == nil {
		JSON(w, 200, v)
	}
	return e
}
func (a *App) cancel(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.access(r); e != nil {
		return e
	}
	id := r.PathValue("id")
	e := a.transaction(r.Context(), func(tx pgx.Tx) error {
		_, e := tx.Exec(r.Context(), "update investigations set status='cancelled' where id=$1", id)
		if e != nil {
			return e
		}
		_, e = tx.Exec(r.Context(), "update jobs set state='cancelled',lease_until=null where id=$1", id)
		if e != nil {
			return e
		}
		_, e = tx.Exec(r.Context(), "update actions set state='invalidated' where investigation=$1 and state in ('draft','approved','rejected')", id)
		if e != nil {
			return e
		}
		return event(r.Context(), tx, id, "cancelled", map[string]string{"note": "Already dispatched external requests require reconciliation."})
	})
	if e == nil {
		JSON(w, 200, map[string]string{"status": "cancelled"})
	}
	return e
}
func (a *App) resume(w http.ResponseWriter, r *http.Request) error {
	if _, e := a.access(r); e != nil {
		return e
	}
	var b struct {
		Information string `json:"information"`
	}
	if e := decode(r, &b); e != nil {
		return e
	}
	if len(b.Information) > 4000 {
		return E(400, "information_too_large")
	}
	id := r.PathValue("id")
	e := a.transaction(r.Context(), func(tx pgx.Tx) error {
		tag, e := tx.Exec(r.Context(), "update investigations set status='queued',symptom=symptom||E'\n'||$2,source_version=(select watermark from services where id=investigations.service) where id=$1 and status in ('waiting_information','failed','partial','completed')", id, b.Information)
		if e != nil {
			return e
		}
		if tag.RowsAffected() != 1 {
			return E(409, "not_resumable")
		}
		_, e = tx.Exec(r.Context(), "update jobs set state='queued',available_at=now(),attempts=0,last_callback=null,result_hash=null where id=$1", id)
		if e != nil {
			return e
		}
		_, e = tx.Exec(r.Context(), "update actions set state='invalidated' where investigation=$1 and state not in ('succeeded','unknown','executing')", id)
		if e != nil {
			return e
		}
		return event(r.Context(), tx, id, "resumed", map[string]string{"information": b.Information})
	})
	if e == nil {
		JSON(w, 202, map[string]string{"id": id})
	}
	return e
}
