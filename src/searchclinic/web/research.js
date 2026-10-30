'use strict';
const element = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
const labels = {no_repair:'수정 없음',saved_first_candidate:'저장 첫 후보',oracle_submitted_candidates_with_noop:'관측 후보 Oracle + 수정 없음'};
fetch('research-replay.json').then(response => response.ok ? response : fetch('research-summary.json')).then(response => {if (!response.ok) throw new Error('기록을 읽을 수 없습니다.'); return response.json();}).then(data => {
  for (const [name, value] of Object.entries(labels).map(([name]) => [name, data.score_report.summaries[name]])) {
    const row = document.createElement('tr'); row.append(element('td', labels[name] || name));
    for (const metric of ['ndcg10','recall10','precision5']) row.append(element('td',value.overall[metric].toFixed(6)));
    document.querySelector('#summary').append(row);
  }
  const choices = document.querySelector('#queries');
  data.queries.forEach((query,index) => {const option = element('option',`${query.query} · 저장 후보 ${query.candidates.length}개`); option.value = index; choices.append(option);});
  const show = () => {
    const query = data.queries[Number(choices.value)]; const detail = document.querySelector('#detail'); detail.replaceChildren();
    detail.append(element('h2',query.query), element('p',`질의 ID: ${query.query_id} · 기존 nDCG@10 ${query.baseline_metrics.ndcg10.toFixed(6)}`),element('p',`기존 검색 순위: ${query.baseline_ranking.join(' → ') || '결과 없음'}`));
    detail.append(element('p','의미 검증: 실제 모델 판정 미실행. 아래 선택 표시는 저장 첫 후보를 적용한 개발 비교 조건입니다.'));
    if (!query.candidates.length) detail.append(element('p','저장된 제출 후보 없음. 미제출 후보까지 없었다는 뜻은 아닙니다.'));
    for (const candidate of query.candidates) {
      const card = document.createElement('article');
      card.append(element('h2',`${candidate.candidate_id.slice(0,12)}${query.selected_candidate_id === candidate.candidate_id ? ' · 첫 후보 조건에서 적용' : ' · 첫 후보 조건에서 미선택'}`));
      const rx=candidate.prescription;
      const changes=[...(rx.synonym_groups||[]).map(g=>g.terms.join(' ↔ ')),...(rx.user_words||[]).map(w=>'사용자 사전: '+w.form),...(rx.compound_expansions||[]).map(c=>c.word+' → '+c.parts.join(' + '))];
      card.append(element('p',changes.join(' / ')),element('p',rx.reasoning));
      card.append(element('p',`적용 후 표적 nDCG@10: ${candidate.target_after.ndcg10.toFixed(6)} · 정상 검색 회귀 ${candidate.healthy_regressed_query_ids.length}건`));
      card.append(element('p',`적용 후 검색 순위: ${candidate.target_rankings.join(' → ') || '결과 없음'}`));
      card.append(element('p','정답을 이용한 개발 회귀 검사 (최종 선택기에는 제공하지 않음)'));
      const gate=candidate.strict_mean_gate;
      card.append(element('p',(gate.accepted?'채택':'기각')+' · '+gate.reason_codes.join(', ')));
      const raw=document.createElement('details');raw.append(element('summary','처방·회귀 검사 원본'),element('pre',JSON.stringify({prescription:rx,gate},null,2)));card.append(raw);
      detail.append(card);
    }
  };
  if (data.queries.length) { choices.addEventListener('change',show); show(); }
  else { document.querySelector('#query-section').hidden=true; document.querySelector('#download').hidden=true; }
  document.querySelector('#run-summary').textContent=`API ${data.costs.api_calls}회 · 검색 ${data.costs.search_calls}회 · 재색인 ${data.costs.reindexes}회 · 실측 ${(data.costs.latency_ms/1000).toFixed(2)}초`;
  document.querySelector('#evidence').textContent = JSON.stringify({study_status:data.study_status,candidate_scope:data.candidate_scope,candidate_selection_bias:data.candidate_selection_bias,source:data.source,source_json:data.source_json,costs:data.costs,limitations:data.limitations},null,2);
  document.querySelector('#report').hidden=false;
  document.querySelector('#load').textContent=data.queries.length ? 'API 호출 없이 저장된 실제 개발 진단 기록을 표시합니다.' : '개발 진단의 실제 집계 결과입니다. 상세 데이터는 공개 승인 전까지 로컬 재현으로 제공합니다.';
}).catch(error => {document.querySelector('#load').textContent=error.message;});
