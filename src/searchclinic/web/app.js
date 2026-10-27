'use strict';
const $=id=>document.getElementById(id);
let records=[],current=null,controller=null,epoch=0;
const labels={supported:'원문 인용 확인',abstain:'판단 보류',invalid:'검증 실패'};
function text(id,value){$(id).textContent=value;}
function node(tag,value,cls){const n=document.createElement(tag);n.textContent=value;if(cls)n.className=cls;return n;}
function status(value){text('status',value);}
function busy(value){$('generate').disabled=value;$('cancel').hidden=!value;$('mode').disabled=value;$('apply').disabled=value||!current?.answer?.prescription||current?.mode!=='live';}
function render(report){
 current=report;$('result').hidden=false;$('download').disabled=false;
 const answer=report.answer||{};const context=report.context||{};const generation=report.generation||{};
 text('query',context.query||'');$('query').value=context.query||'';$('problem').value=context.problem||'';
 text('result-state',labels[answer.status]||'생성 실패');
 text('tokens',(context.analysis?.tokens||[]).map(t=>`${t.token} / ${t.tag}`).join(' · ')||'없음');
 text('hits',(context.search?.results||[]).map(h=>h.name).join(' / ')||'검색 결과 없음');
 text('metadata',`${generation.model||'모델 응답 없음'} · ${generation.latency_ms??'—'}ms · 추정 $${generation.estimated_usd??'—'} · ${report.condition||'retrieved'}`);
 text('summary',answer.summary||report.error||'응답을 받지 못했습니다.');
 $('patches').replaceChildren(...(answer.patches||[]).map(p=>node('div',`${p.kind}  ${p.terms.join(' → ')}`,'patch')));
 const gate=report.gate;
 text('gate-text',gate?`${gate.accepted?'채택':'기각'} · 표적 nDCG ${gate.target_ndcg_before} → ${gate.target_ndcg_after}\n${gate.feedback||''}`:report.gate_error?'이 질의는 평가셋 밖이므로 검증할 수 없습니다.':answer.prescription?'수정 후보가 있습니다. 전체 평가셋 검사를 거쳐야 적용됩니다.':'검증할 수정 후보가 없습니다.');
 $('apply').hidden=report.mode!=='live';$('apply').disabled=!answer.prescription||Boolean(gate);
 $('citations').replaceChildren();
 for(const doc of context.documents||[]){
  const section=node('article','','document');section.append(node('div',doc.id,'doc-id'),node('h3',doc.title));
  const evidence=(answer.evidence||[]).filter(e=>e.doc_id===doc.id);
  for(const e of evidence)section.append(node('blockquote',e.quote));
  if(!evidence.length)section.append(node('p','검색에 포함됐으나 답변에서 인용하지 않은 문서','small'));
  const detail=node('details','');detail.append(node('summary','제공된 본문 보기'),node('pre',doc.body));section.append(detail,node('p',doc.source,'small'));$('citations').append(section);
 }
 if(!(context.documents||[]).length)$('citations').append(node('p','이 조건에서는 문서를 제공하지 않았습니다.','empty'));
 status(report.mode==='live'?'새 API 생성 결과입니다. 원문 확인과 수정안 검증 결과를 구분해 보세요.':'저장된 실제 실행 기록입니다. 현재 새 계산을 수행하지 않습니다.');
}
function selectRecord(index){epoch++;current=null;document.querySelectorAll('#cases button').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));render({...records[index],mode:'replay'});}
async function load(){
 try{
  const response=await fetch('replay.json');if(!response.ok)throw Error('아직 저장된 실제 생성 기록이 없습니다.');
  const data=await response.json();records=data.rows||[];$('cases').replaceChildren();
  records.forEach((r,i)=>{const b=node('button',`${r.case_id} · ${r.context.query}`);b.type='button';b.append(node('small',`${r.condition==='no_documents'?'근거 제거':'운영 지식 제공'} · ${labels[r.answer?.status]||'생성 오류'}`));b.addEventListener('click',()=>selectRecord(i));$('cases').append(b);});
  if(records.length)selectRecord(0);else throw Error('저장된 생성 기록이 비어 있습니다.');
 }catch(e){$('cases').replaceChildren(node('p','저장 기록 없음','empty'));status(e.message);}
 setMode();
}
function setMode(){
 const live=$('mode').value==='live';epoch++;current=null;$('result').hidden=true;$('download').disabled=true;
 $('live-controls').hidden=!live;$('query').readOnly=!live;$('problem').readOnly=!live;
 $('cases').inert=live;
 text('mode-note',live?'로컬 서버에서 새 API 요청이 발생합니다. 승인된 예산 범위에서만 실행하세요.':'이 화면에서는 새 API 요청이 발생하지 않습니다.');
 if(live){status('로컬 API 서버와 운영 토큰이 필요합니다. 공개 정적 화면에서는 생성할 수 없습니다.');}
 else if(records.length)selectRecord(0);
}
$('mode').addEventListener('change',setMode);
async function request(path,body,signal){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+$('token').value},body:body?JSON.stringify(body):undefined,signal});
 let data;try{data=await response.json();}catch{throw Error('로컬 API 응답을 받지 못했습니다. 로컬 서버 주소에서 실행해 주세요.');}
 if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:`요청을 처리하지 못했습니다 (${response.status}).`);return data;
}
$('query-form').addEventListener('submit',async event=>{
 event.preventDefault();if($('mode').value!=='live'||controller)return;
 current=null;$('result').hidden=true;$('download').disabled=true;
 const id=++epoch;controller=new AbortController();busy(true);status('운영 지식을 검색하고 설명을 생성하고 있습니다.');
 try{const r=await request('/explanations',{query:$('query').value,problem:$('problem').value},controller.signal);if(id===epoch)render(r);}
 catch(e){if(id===epoch)status(e.name==='AbortError'?'수신을 취소했습니다. 서버에서 이미 시작한 생성과 비용은 취소되지 않을 수 있습니다.':e.message);}
 finally{controller=null;busy(false);}
});
$('cancel').addEventListener('click',()=>controller?.abort());
$('apply').addEventListener('click',async()=>{
 if(!current||current.mode!=='live')return;const id=epoch;$('apply').disabled=true;status('전체 평가셋으로 회귀를 검사하고 있습니다.');
 try{const r=await request(`/explanations/${current.id}/apply`);if(id===epoch)render(r);}
 catch(e){if(id===epoch){status(e.message);$('apply').disabled=false;}}
});
$('download').addEventListener('click',()=>{
 if(!current)return;const blob=new Blob([JSON.stringify(current,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=node('a','');a.href=url;a.download='search-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
load();
