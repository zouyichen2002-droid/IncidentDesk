package main

import (
	"context"
	"go.opentelemetry.io/otel"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"incidentdesk/internal/app"
	"log/slog"
	"net/http"
	_ "net/http/pprof"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	otel.SetTracerProvider(sdktrace.NewTracerProvider(sdktrace.WithBatcher(app.TraceExporter{})))
	a, e := app.New(ctx)
	if e != nil {
		slog.Error("startup", "error", e)
		os.Exit(1)
	}
	defer a.DB.Close()
	addr := os.Getenv("LISTEN_ADDR")
	if addr == "" {
		addr = ":8080"
	}
	srv := &http.Server{Addr: addr, Handler: a.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 95 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16384}
	go a.RunActions(ctx)
	go a.RunDataQueries(ctx)
	if os.Getenv("PPROF_ADDR") != "" {
		go http.ListenAndServe(os.Getenv("PPROF_ADDR"), nil)
	}
	go func() {
		slog.Info("listening", "addr", addr)
		if e := srv.ListenAndServe(); e != nil && e != http.ErrServerClosed {
			slog.Error("server", "error", e)
			stop()
		}
	}()
	<-ctx.Done()
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdown)
}
