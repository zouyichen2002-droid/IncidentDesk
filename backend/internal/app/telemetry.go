package app

import (
	"context"
	"encoding/json"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"log/slog"
)

// Durable business events carry task/action IDs; this exporter records OpenTelemetry
// span identifiers and timings without HTTP bodies, tokens or private model reasoning.
type TraceExporter struct{}

func (TraceExporter) ExportSpans(_ context.Context, spans []sdktrace.ReadOnlySpan) error {
	for _, s := range spans {
		attrs := map[string]any{}
		for _, a := range s.Attributes() {
			attrs[string(a.Key)] = a.Value.AsInterface()
		}
		b, _ := json.Marshal(attrs)
		slog.Info("trace", "trace_id", s.SpanContext().TraceID().String(), "span_id", s.SpanContext().SpanID().String(), "parent", s.Parent().SpanID().String(), "name", s.Name(), "duration_ms", float64(s.EndTime().Sub(s.StartTime()).Microseconds())/1000, "attributes", string(b))
	}
	return nil
}
func (TraceExporter) Shutdown(context.Context) error { return nil }
