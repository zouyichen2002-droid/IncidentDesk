package app

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

func kubeRequest(ctx context.Context, method, path string, body any) ([]byte, error) {
	token, e := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/token")
	if e != nil {
		return nil, E(503, "sandbox_requires_kubernetes")
	}
	ca, e := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
	if e != nil {
		return nil, e
	}
	roots := x509.NewCertPool()
	roots.AppendCertsFromPEM(ca)
	client := &http.Client{Timeout: 5 * time.Second, Transport: &http.Transport{TLSClientConfig: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12}}}
	defer client.CloseIdleConnections()
	var b io.Reader
	if body != nil {
		raw, _ := json.Marshal(body)
		b = bytes.NewReader(raw)
	}
	r, e := http.NewRequestWithContext(ctx, method, "https://kubernetes.default.svc"+path, b)
	if e != nil {
		return nil, e
	}
	r.Header.Set("Authorization", "Bearer "+string(token))
	r.Header.Set("Content-Type", "application/json")
	resp, e := client.Do(r)
	if e != nil {
		return nil, e
	}
	defer resp.Body.Close()
	raw, e := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if e != nil {
		return nil, e
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("cluster_api_%d", resp.StatusCode)
	}
	return raw, nil
}
func (a *App) sandbox(ctx context.Context, records []map[string]any) (any, error) {
	if len(records) > 1000 {
		return nil, E(400, "sandbox_input_limit")
	}
	raw, _ := json.Marshal(records)
	if len(raw) > 262144 {
		return nil, E(400, "sandbox_input_limit")
	}
	name := "analysis-" + ID()
	ns := "incident-sandbox"
	cm := map[string]any{"apiVersion": "v1", "kind": "ConfigMap", "metadata": map[string]string{"name": name}, "immutable": true, "data": map[string]string{"records.json": string(raw)}}
	if _, e := kubeRequest(ctx, "POST", "/api/v1/namespaces/"+ns+"/configmaps", cm); e != nil {
		return nil, e
	}
	defer kubeRequest(context.Background(), "DELETE", "/api/v1/namespaces/"+ns+"/configmaps/"+name, nil)
	spec := map[string]any{"apiVersion": "batch/v1", "kind": "Job", "metadata": map[string]string{"name": name}, "spec": map[string]any{"backoffLimit": 0, "activeDeadlineSeconds": 10, "ttlSecondsAfterFinished": 60, "template": map[string]any{"metadata": map[string]any{"labels": map[string]string{"app": "sandbox"}}, "spec": map[string]any{"restartPolicy": "Never", "automountServiceAccountToken": false, "securityContext": map[string]any{"runAsNonRoot": true, "runAsUser": 65532, "runAsGroup": 65532, "fsGroup": 65532}, "containers": []any{map[string]any{"name": "analyze", "image": "incidentdesk-sandbox:0.1.0", "imagePullPolicy": "IfNotPresent", "resources": map[string]any{"requests": map[string]string{"cpu": "50m", "memory": "32Mi"}, "limits": map[string]string{"cpu": "500m", "memory": "64Mi"}}, "securityContext": map[string]any{"readOnlyRootFilesystem": true, "allowPrivilegeEscalation": false, "capabilities": map[string]any{"drop": []string{"ALL"}}}, "volumeMounts": []any{map[string]any{"name": "input", "mountPath": "/input", "readOnly": true}, map[string]any{"name": "output", "mountPath": "/output"}}}}, "volumes": []any{map[string]any{"name": "input", "configMap": map[string]string{"name": name}}, map[string]any{"name": "output", "emptyDir": map[string]string{"sizeLimit": "1Mi"}}}}}}}
	if _, e := kubeRequest(ctx, "POST", "/apis/batch/v1/namespaces/"+ns+"/jobs", spec); e != nil {
		return nil, e
	}
	defer kubeRequest(context.Background(), "DELETE", "/apis/batch/v1/namespaces/"+ns+"/jobs/"+name, map[string]string{"propagationPolicy": "Background"})
	deadline := time.NewTimer(15 * time.Second)
	defer deadline.Stop()
	ticker := time.NewTicker(300 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-deadline.C:
			return nil, E(504, "sandbox_timeout")
		case <-ticker.C:
			raw, e := kubeRequest(ctx, "GET", "/api/v1/namespaces/"+ns+"/pods?labelSelector=job-name%3D"+name, nil)
			if e != nil {
				return nil, e
			}
			var pods struct {
				Items []struct {
					Metadata struct {
						Name string `json:"name"`
					} `json:"metadata"`
					Status struct {
						Phase string `json:"phase"`
					} `json:"status"`
				} `json:"items"`
			}
			if json.Unmarshal(raw, &pods) != nil {
				continue
			}
			for _, p := range pods.Items {
				if p.Status.Phase == "Failed" {
					return nil, E(422, "sandbox_failed")
				}
				if p.Status.Phase == "Succeeded" {
					raw, e := kubeRequest(ctx, "GET", "/api/v1/namespaces/"+ns+"/pods/"+p.Metadata.Name+"/log", nil)
					if e != nil {
						return nil, e
					}
					var out any
					if e = json.Unmarshal(raw, &out); e != nil {
						return nil, e
					}
					return out, nil
				}
			}
		}
	}
}
