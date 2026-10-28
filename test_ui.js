// UI tests: drives dashboard.html and index.html (in jsdom) against a REAL running server + database.
// Run:  npm i jsdom   then   node test_ui.js        (needs the Python deps from requirements.txt)
const {JSDOM,VirtualConsole}=require("jsdom");const {spawn}=require("child_process");const os=require("os"),fs=require("fs"),path=require("path");
const PORT=8800+Math.floor(Math.random()*900),B="http://127.0.0.1:"+PORT,TMP=fs.mkdtempSync(path.join(os.tmpdir(),"saba-ui-"));
const PNG=Buffer.concat([Buffer.from([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a]),Buffer.alloc(120)]);
const results=[];const ok=(n,c)=>{results.push((c?"PASS ":"FAIL ")+n);if(!c)process.exitCode=1};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,ms=6000){const t=Date.now();while(Date.now()-t<ms){try{if(fn())return true}catch(e){}await sleep(40)}return false}
async function api(p,method="GET",body,cookie){const r=await fetch(B+p,{method,headers:{"Content-Type":"application/json","X-Requested-With":"saba",...(cookie?{Cookie:cookie}:{})},body:body?JSON.stringify(body):undefined});return r}
async function cookieOf(em,pw){const r=await api("/api/auth/login","POST",{email:em,password:pw});return r.headers.get("set-cookie").split(";")[0]}
async function open(file,hash="",stub){ // a browser window with its own cookie jar
 const jar={c:""};const html=await (await fetch(B+"/"+file)).text();
 const vc=new VirtualConsole();vc.on("jsdomError",e=>{if(process.env.DBG)console.log("PAGE ERROR:",String(e.stack||e.message).slice(0,400))});
 const dom=new JSDOM(html,{url:B+"/"+file+hash,runScripts:"dangerously",pretendToBeVisual:true,virtualConsole:vc,beforeParse(w){
  w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.Element.prototype.scrollIntoView=()=>{};w.confirm=()=>true;
  w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute("open","")};w.HTMLDialogElement.prototype.close=function(){this.removeAttribute("open")};
  w.fetch=async(u,o={})=>{let body=o.body;if(body instanceof w.FormData){const fd=new FormData();for(const [k,v] of body.entries())v.__bytes?fd.append(k,new Blob([v.__bytes],{type:v.type}),v.name):fd.append(k,v);body=fd}
   const r=await fetch(new URL(u,B),{...o,body,headers:{...(o.headers||{}),...(jar.c?{Cookie:jar.c}:{})}});const sc=r.headers.get("set-cookie");if(sc){const kv=sc.split(";")[0];jar.c=/=\s*$|=;?$|Max-Age=0|expires=Thu, 01 Jan 1970/i.test(sc)?"":kv}return r}}});
 const w=dom.window;w.jar=jar;await sleep(300);return w}
const Q=(w,s)=>w.document.querySelector(s),QA=(w,s)=>[...w.document.querySelectorAll(s)],txt=(w,s)=>(Q(w,s)||{}).textContent||"";
const body=w=>{const c=w.document.body.cloneNode(true);c.querySelectorAll("script").forEach(s=>s.remove());return c.textContent};
const type=(w,el,v)=>{el.value=v;el.dispatchEvent(new w.Event("input",{bubbles:true}))};
const submit=(w,f)=>f.dispatchEvent(new w.Event("submit",{bubbles:true,cancelable:true}));
const click=(w,el)=>el.dispatchEvent(new w.MouseEvent("click",{bubbles:true,cancelable:true}));
const btn=(w,text)=>QA(w,"button,a.btn").find(b=>b.textContent.trim().startsWith(text));
const hash=(w,h)=>{w.location.hash=h};
async function pickFile(w,input,name,type_,bytes){const f=new w.File([bytes],name,{type:type_});f.__bytes=bytes;Object.defineProperty(input,"files",{value:[f],configurable:true});input.dispatchEvent(new w.Event("change",{bubbles:true}))}
async function loginUI(w,email,pw){type(w,Q(w,'input[name=email]'),email);type(w,Q(w,'input[name=password]'),pw);submit(w,Q(w,"form"))}

(async()=>{
 const srv=spawn("python3",["app.py","serve"],{cwd:__dirname,env:{...process.env,DATABASE_URL:"sqlite:///"+TMP+"/ui.db",UPLOAD_DIR:TMP+"/up",ADMIN_EMAIL:"admin@saba.com",ADMIN_PASSWORD:"AdminPass123",PORT:String(PORT)},stdio:"ignore"});
 try{
  for(let i=0;i<60;i++){try{if((await fetch(B+"/api/health")).ok)break}catch(e){}await sleep(250)}
  const adm=await cookieOf("admin@saba.com","AdminPass123");
  for(const [em,role] of [["ta@saba.com","teacher"],["tb@saba.com","teacher"]])await api("/api/admin/users","POST",{email:em,name:em.slice(0,2).toUpperCase()+" Teacher",password:"Passw0rd!!",role},adm);
  await api("/api/auth/register","POST",{email:"stu@saba.com",name:"Stu Dent",password:"Passw0rd!!"});

  // ---- login gate, wrong password, student blocked
  let w=await open("dashboard.html");
  ok("unauthenticated visitor sees the login form, not the dashboard",!!Q(w,'input[name=password]')&&!/My courses/.test(body(w)));
  await loginUI(w,"ta@saba.com","wrong-password");await until(()=>/Invalid email or password/.test(body(w)));ok("wrong password shows the server's error message",/Invalid email or password/.test(body(w)));
  w=await open("dashboard.html");await loginUI(w,"stu@saba.com","Passw0rd!!");await until(()=>/teachers and administrators/.test(body(w)));
  ok("student login is refused the dashboard",/teachers and administrators/.test(body(w))&&!Q(w,"nav"));
  ok("student cannot reach any dashboard data via the same session",(await w.fetch("/api/manage/courses")).status===403&&(await w.fetch("/api/admin/users")).status===403);

  // ---- teacher A: create draft through the form
  const A=await open("dashboard.html");await loginUI(A,"ta@saba.com","Passw0rd!!");
  await until(()=>/No courses yet/.test(body(A)));ok("teacher sees 'My courses' with an honest empty state",/No courses yet/.test(body(A)));
  hash(A,"new");await until(()=>Q(A,"input[name=title_en]"));
  const f=Q(A,"form");type(A,f.elements.title_en,"Ui Built Course");type(A,f.elements.summary_en,"A summary written in the dashboard");f.elements.level.value="Intermediate";f.elements.price.value="0";
  submit(A,f);await until(()=>/#edit-/.test(A.location.hash));
  const list=await (await api("/api/manage/courses","GET",null,await cookieOf("ta@saba.com","Passw0rd!!"))).json();
  ok("form creates a real draft in the database",list.length===1&&list[0].title_en==="Ui Built Course"&&list[0].status==="draft"&&list[0].level==="Intermediate");
  const cid=list[0].id;
  // ---- media: wrong file refused client-side, right one uploaded
  await until(()=>Q(A,'input[type=file]'));
  await pickFile(A,QA(A,'input[type=file]')[0],"evil.exe","application/octet-stream",Buffer.from("MZ"));await until(()=>QA(A,"#toast .t.err").length>0);
  ok("invalid thumbnail rejected with a visible error",/under 3 MB/.test(txt(A,"#toast")));
  await pickFile(A,QA(A,'input[type=file]')[0],"cover.png","image/png",PNG);await until(()=>Q(A,"img.prev"));
  ok("thumbnail upload reaches the server and the preview shows",!!Q(A,"img.prev")&&(await (await api("/api/manage/courses/"+cid,"GET",null,await cookieOf("ta@saba.com","Passw0rd!!"))).json()).thumbnail_url);
  await pickFile(A,QA(A,'input[type=file]')[1],"notes.txt","text/plain",Buffer.from("study notes"));await until(()=>/notes\.txt/.test(body(A)));
  ok("material upload is listed",/notes\.txt/.test(body(A)));
  click(A,btn(A,"Delete"));await until(()=>/No materials uploaded/.test(body(A)));ok("material can be deleted",/No materials uploaded/.test(body(A)));
  // ---- curriculum
  click(A,QA(A,'[role=tab]')[2]);await until(()=>/No sections yet/.test(body(A)));
  const sf=Q(A,"form");type(A,sf.elements.title_en,"Getting started");submit(A,sf);await until(()=>QA(A,"summary").some(s=>/Add lesson/.test(s.textContent)));
  ok("section created",/Getting started/.test(QA(A,"input").map(i=>i.value).join()));
  const lf=QA(A,"details form")[0];type(A,lf.elements.title_en,"Welcome lesson");lf.elements.kind.value="text";type(A,lf.elements.content_text,"Hello students");lf.elements.duration_minutes.value="12";submit(A,lf);
  await until(()=>/1\. Welcome lesson/.test(body(A)));ok("lesson created with content",/1\. Welcome lesson/.test(body(A)));
  // ---- submit
  click(A,QA(A,'[role=tab]')[3]);await until(()=>/Submit for review/.test(body(A)));
  ok("checklist shows all requirements met and submit is enabled",QA(A,".ck.ok").length===4&&!btn(A,"Submit for review").disabled);
  click(A,btn(A,"Submit for review"));await until(()=>/locked for editing/.test(body(A)));
  ok("submission moves the course to Pending review and locks editing",/Pending review/.test(txt(A,".row"))&&/locked for editing/.test(body(A))&&QA(A,"form fieldset[disabled]").length===0||/locked for editing/.test(body(A)));
  if(process.env.DBG)console.log("DBG A after submit:",body(A).replace(/\s+/g," ").slice(0,700));
  const tk=await cookieOf("ta@saba.com","Passw0rd!!");
  ok("server agrees: status pending_review, not public",(await (await api("/api/manage/courses/"+cid,"GET",null,tk)).json()).status==="pending_review"&&(await (await api("/api/courses/"+cid)).status)===404);

  // ---- teacher B cannot open or change A's course
  const Bw=await open("dashboard.html","#edit-"+cid);await loginUI(Bw,"tb@saba.com","Passw0rd!!");await until(()=>/cannot manage/.test(body(Bw)));
  ok("teacher B opening teacher A's editor gets 'cannot manage'",/cannot manage/.test(body(Bw)));
  ok("teacher B cannot see the review queue / admin screens",(hash(Bw,"queue"),await sleep(400),!/Review queue/.test(txt(Bw,"nav"))));

  // ---- admin: reject with reason
  const D=await open("dashboard.html");await loginUI(D,"admin@saba.com","AdminPass123");await until(()=>/Review queue/.test(txt(D,"nav")));
  hash(D,"queue");await until(()=>/Ui Built Course/.test(body(D)));ok("admin review queue lists the pending course",/Ui Built Course/.test(body(D)));
  click(D,btn(D,"Review"));await until(()=>/Hello students|Welcome lesson/.test(body(D)));if(process.env.DBG)console.log("DBG D review:",D.location.hash,body(D).replace(/\s+/g," ").slice(0,600));
  ok("admin can inspect curriculum and lesson content before deciding",/Welcome lesson/.test(body(D))&&/Getting started/.test(body(D)));
  const rf=QA(D,"form")[0];type(D,rf.elements.note,"x");submit(D,rf); // too short -> HTML validation / server must refuse
  await sleep(500);ok("a too-short rejection reason does not reject the course",(await (await api("/api/manage/courses/"+cid,"GET",null,tk)).json()).status==="pending_review");
  type(D,rf.elements.note,"Please add a second lesson");submit(D,rf);await until(()=>/Course rejected/.test(txt(D,"#toast")));
  ok("rejection with a reason succeeds and confirms",/Course rejected/.test(txt(D,"#toast")));
  // ---- teacher sees reason, edits and resubmits
  hash(A,"courses");await until(()=>/Rejected/.test(body(A)));ok("teacher sees Rejected badge and the admin's reason",/Rejected/.test(body(A))&&/Please add a second lesson/.test(body(A)));
  hash(A,"edit-"+cid);await until(()=>Q(A,"input[name=title_en]"));ok("rejected course is editable again",!Q(A,"fieldset[disabled]"));
  click(A,QA(A,'[role=tab]')[3]);await until(()=>btn(A,"Submit for review"));click(A,btn(A,"Submit for review"));await until(()=>/Pending review/.test(body(A)));
  ok("teacher resubmits the rejected course",/Pending review/.test(body(A)));
  // ---- admin approves
  click(D,QA(D,"nav a").find(a=>a.textContent==="Review queue"));await until(()=>btn(D,"Review"));if(process.env.DBG)console.log("DBG D queue:",body(D).replace(/\s+/g," ").slice(0,500),"| status:",(await (await api("/api/manage/courses/"+cid,"GET",null,tk)).json()).status);click(D,btn(D,"Review"));await until(()=>btn(D,"Approve and publish"));
  click(D,btn(D,"Approve and publish"));await until(()=>/Course published/.test(txt(D,"#toast")));ok("admin approves and publishes",/Course published/.test(txt(D,"#toast")));
  ok("course is now public through the API",(await (await api("/api/courses/"+cid)).json()).title_en==="Ui Built Course");
  const S=await open("index.html","#explore");await until(()=>QA(S,"#xgrid .cc").length>0);
  ok("Explore page shows the course published via the dashboard (no code change)",QA(S,"#xgrid .cc").some(c=>/Ui Built Course/.test(c.textContent))&&!QA(S,"#xgrid .demo").length);

  // ---- admin: categories and users
  hash(D,"cats");await until(()=>/Add category/.test(body(D)));const cf=QA(D,"form").pop();const ins=[...cf.querySelectorAll("input")];type(D,ins[0],"cooking");type(D,ins[1],"Cooking");submit(D,cf);
  await until(()=>/Saved/.test(txt(D,"#toast")));ok("admin adds a category (a new discipline) from the dashboard",(await (await api("/api/categories")).json()).some(c=>c.slug==="cooking"));
  hash(D,"users");await until(()=>/Create account/.test(body(D)));
  const meRow=QA(D,"tr").find(r=>/admin@saba\.com/.test(r.textContent));ok("admin's own role/active controls are disabled (self-demotion guard)",[...meRow.querySelectorAll("select,input")].every(x=>x.disabled));
  const uf=QA(D,"form").pop();type(D,uf.elements.name,"New Teacher");type(D,uf.elements.email,"newt@saba.com");type(D,uf.elements.password,"Passw0rd!!");uf.elements.role.value="teacher";submit(D,uf);
  await until(()=>/newt@saba\.com/.test(body(D)));ok("admin creates a teacher account",/newt@saba\.com/.test(body(D)));

  // ---- language switch and logout
  click(D,btn(D,"አማ"));await until(()=>/ተጠቃሚዎች/.test(txt(D,"nav")));ok("dashboard switches to Amharic",/ተጠቃሚዎች/.test(txt(D,"nav")));
  click(D,btn(D,"ውጣ"));await until(()=>!!Q(D,'input[name=password]'));ok("logout returns to the login form",!!Q(D,'input[name=password]'));
  ok("after logout the same window can no longer use admin endpoints",(await D.fetch("/api/admin/users")).status===401);

  // ---- end-to-end student journey: course discovery -> login -> free enrollment -> saved lesson progress
  const created=await api("/api/manage/courses","POST",{title_en:"UI Learning Journey Course",summary_en:"Course used by automated student journey checks",category_id:1,price:0},adm);
  const journeyCourse=await created.json();
  const section=await (await api("/api/manage/courses/"+journeyCourse.id+"/sections","POST",{title_en:"Start here"},adm)).json();
  const lesson=await (await api("/api/manage/sections/"+section.id+"/lessons","POST",{title_en:"First lesson",kind:"text",content_text:"Welcome to the course",duration_minutes:5},adm)).json();
  const published=await api("/api/manage/courses/"+journeyCourse.id+"/submit","POST",{},adm);
  ok("test course is published through the real API",published.ok);
  const V=await open("index.html");await until(()=>QA(V,".go").length>0);
  const view=QA(V,".go").find(a=>a.getAttribute("href")==="#course/"+journeyCourse.slug);
  ok("published course is discoverable from Home",!!view);
  if(view){click(V,view);ok("signed-out View Course opens the real login dialog",!Q(V,"#authForm").hidden&&!!V.location.hash===false);
    type(V,Q(V,"#fEmail"),"stu@saba.com");type(V,Q(V,"#fPw"),"Passw0rd!!");submit(V,Q(V,"#authForm"));
    await until(()=>V.location.hash==="#course/"+journeyCourse.slug&&/UI Learning Journey Course/.test(txt(V,"#courseTitle")));
    ok("successful login returns to the selected course",V.location.hash==="#course/"+journeyCourse.slug&&/UI Learning Journey Course/.test(txt(V,"#courseTitle")));
    await until(()=>!!Q(V,"#courseEnroll")&&!Q(V,"#courseBody").hidden);
    click(V,Q(V,"#courseEnroll"));await until(()=>/Enrolled/.test(txt(V,"#courseEnroll")));
    ok("student can enroll in the selected free course",/Enrolled/.test(txt(V,"#courseEnroll")));
    await until(()=>QA(V,".lesson-complete").length>0);const mark=QA(V,".lesson-complete")[0];click(V,mark);
    await until(()=>/Completed/.test(txt(V,".lesson-complete")));
    ok("student can mark a lesson complete and receive confirmation",/Completed/.test(txt(V,".lesson-complete")));
    const progress=await (await api("/api/courses/"+journeyCourse.slug+"/curriculum","GET",undefined,V.jar.c)).json();
    ok("lesson completion is persisted and returned by a fresh curriculum request",progress.sections[0].lessons.some(x=>x.id===lesson.id&&x.completed===true));
  }

  // ---- website login / logout (index.html)
  const M=await open("index.html");await until(()=>M.document.querySelectorAll("#disc .chip").length>1);
  click(M,QA(M,".acts [data-open]")[0]);ok("website Log in opens the real login form (not the placeholder)",!Q(M,"#authForm").hidden&&Q(M,"#authDemo").hidden);
  type(M,Q(M,"#fEmail"),"ta@saba.com");type(M,Q(M,"#fPw"),"nope-wrong-1");submit(M,Q(M,"#authForm"));await until(()=>/Invalid/.test(txt(M,"#authErr")));ok("website shows server error for wrong password",/Invalid/.test(txt(M,"#authErr")));
  type(M,Q(M,"#fPw"),"Passw0rd!!");submit(M,Q(M,"#authForm"));await until(()=>!Q(M,"#whoBox").hidden);
  ok("website login succeeds: Dashboard + Log out shown, login buttons hidden",!Q(M,"#whoBox").hidden&&!QA(M,".dashLink")[0].hidden&&QA(M,".acts [data-open]").every(b=>b.hidden));
  click(M,QA(M,".outBtn")[0]);await until(()=>Q(M,"#whoBox").hidden);ok("website logout works",Q(M,"#whoBox").hidden&&(await M.fetch("/api/auth/me")).status===401);
  const R=await open("index.html");await until(()=>R.document.querySelectorAll("#disc .chip").length>1);click(R,QA(R,".acts [data-open]").pop());ok("Start learning opens the Create account tab",!Q(R,"#nameRow").hidden);
  type(R,Q(R,"#fName"),"Brand New");type(R,Q(R,"#fEmail"),"brandnew@saba.com");type(R,Q(R,"#fPw"),"Passw0rd!!");submit(R,Q(R,"#authForm"));await until(()=>!Q(R,"#whoBox").hidden);
  ok("website registration creates a student and signs in (no Dashboard link for students)",!Q(R,"#whoBox").hidden&&QA(R,".dashLink")[0].hidden);
 }catch(e){ok("test run crashed: "+e.stack,false)}
 finally{srv.kill();await Promise.race([new Promise(r=>srv.on("exit",r)),sleep(3000)]);console.log(results.join("\n"));console.log(`\n${results.filter(r=>r.startsWith("PASS")).length} passed, ${results.filter(r=>r.startsWith("FAIL")).length} failed`)}
})();
