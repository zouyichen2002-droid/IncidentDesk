package app
import("context";"encoding/json";"net/http";"net/http/httptest";"strings";"testing";"github.com/coreos/go-oidc/v3/oidc")
func TestApprovalInvalidationAndRevocation(t *testing.T){a:=testApp(t);ctx:=context.Background();a.verifier=oidc.NewVerifier("http://demo:8090",oidc.NewRemoteKeySet(ctx,"http://localhost:8090/jwks"),&oidc.Config{ClientID:"incidentdesk"});response,e:=http.Post("http://localhost:8090/token","application/json",strings.NewReader(`{"username":"alice","password":"demo-password"}`));if e!=nil{t.Fatal(e)};defer response.Body.Close();var tok struct{Token string `json:"access_token"`};if e=json.NewDecoder(response.Body).Decode(&tok);e!=nil{t.Fatal(e)};id:=seedJob(t,a);_,e=a.DB.Exec(ctx,"update investigations set status='completed',report='{\"facts\":[],\"evidence\":[],\"candidates\":[]}' where id=$1",id);if e!=nil{t.Fatal(e)}
 call:=func(handler func(http.ResponseWriter,*http.Request)error,body,decision string)error{r:=httptest.NewRequest("POST","/test",strings.NewReader(body));r.Header.Set("Authorization","Bearer "+tok.Token);r.SetPathValue("id",id);r.SetPathValue("decision",decision);return handler(httptest.NewRecorder(),r)}
 if e=call(a.draft,`{"version":0,"title":"Test incident","body":"Evidence and next steps"}`,"");e!=nil{t.Fatal(e)}
 if e=call(a.decide,`{"version":1}`,"approve");e!=nil{t.Fatal(e)}
 if e=call(a.draft,`{"version":1,"title":"Changed incident","body":"Different approved content"}`,"");e!=nil{t.Fatal(e)}
 if e=call(a.decide,`{"version":1}`,"approve");e==nil{t.Fatal("old approval accepted")}
 var state string;var version int
 if e=a.DB.QueryRow(ctx,"select state,version from actions where investigation=$1",id).Scan(&state,&version);e!=nil{t.Fatal(e)};if state!="draft"||version!=2{t.Fatalf("edit did not invalidate %s/%d",state,version)}
 if e=call(a.decide,`{"version":2}`,"approve");e!=nil{t.Fatal(e)}
 var posts int;stub:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){if r.Method=="POST"{posts++};w.WriteHeader(500)}));defer stub.Close();a.HTTP=stub.Client();t.Setenv("GITHUB_API_URL",stub.URL)
 _,e=a.DB.Exec(ctx,"update services set watermark=watermark+1 where id='svc-17'");if e!=nil{t.Fatal(e)}
 t.Cleanup(func(){_,_=a.DB.Exec(ctx,"update services set watermark=1 where id='svc-17'")})
 a.actionStep(ctx);if e=a.DB.QueryRow(ctx,"select state from actions where investigation=$1",id).Scan(&state);e!=nil{t.Fatal(e)};if state!="invalidated"||posts!=0{t.Fatal("stale evidence dispatched",state,posts)}
 // Remove original investigator's membership while preserving the signed token.
 _,e=a.DB.Exec(ctx,"delete from members where subject='alice' and team='orders'");if e!=nil{t.Fatal(e)}
 t.Cleanup(func(){_,_=a.DB.Exec(ctx,"insert into members values('alice','orders','approver') on conflict do nothing")})
 if e=call(a.get,`{}`,"");e==nil{t.Fatal("revoked report returned")}
 t.Log("Editing approved content invalidates approval; new source watermark prevents dispatch; live membership overrides existing token.")
}
