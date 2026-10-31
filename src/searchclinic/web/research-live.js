'use strict';
(async () => {
  const node = (tag, text) => {const el = document.createElement(tag); el.textContent = text; return el;};
  const names = {no_repair:'No Repair', rules_plus:'RulesPlus · 정답 gate 없음', first_valid:'저장 scripted 첫 유효 후보',
    'pair:1':'Pair · 1회', 'pair:2':'Pair · 2회', 'context:1':'Context · 1회', 'context:2':'Context · 2회', 'rubric:1':'Rubric · 1회', 'rubric:2':'Rubric · 2회'};
  const reasons = {invalid_citation:'인용 위치 불일치', non_equivalent_relation:'동등 관계로 판단하지 않음',
    same_referent_not_confirmed:'같은 대상 확인 부족', scope_not_preserved:'의미 범위 보존 확인 부족',
    context_support_not_confirmed:'문맥 근거 확인 부족', low_confidence:'고정 confidence 기준 미달'};
  const fmt = x => typeof x === 'number' ? x.toFixed(6) : '—';
  try {
    const response = await fetch('research-v5-live-summary.json');
    if (!response.ok) throw Error('실제 LLM 집계 기록을 읽을 수 없습니다.');
    const data = await response.json();
    if (data.version !== 'v5-live-public-summary-1') throw Error('지원하지 않는 집계 형식입니다.');
    for (const [name, title] of Object.entries(names)) {
      const a = data.arms[name]; const row = node('tr',''); row.append(node('td',title));
      for (const metric of ['ndcg10','recall10','precision5']) row.append(node('td',fmt(a.metrics.overall[metric])));
      row.append(node('td',`${a.apply_count}/${a.hold_count}`), node('td',String(a.normal_regression_count)),
        node('td',a.useful_candidates_not_selected === null ? '—' : String(a.useful_candidates_not_selected)));
      document.querySelector('#live-summary').append(row);
    }
    const cost = data.costs;
    document.querySelector('#live-cost').textContent = `${data.model_id} · 실제 ${cost.provider_calls}회 · 입력 ${cost.input_tokens.toLocaleString()} / 출력 ${cost.output_tokens.toLocaleString()}토큰 · 사용량 기준 추정 $${cost.usage_cost_estimate_usd.toFixed(7)} · ${(cost.wall_latency_ms/1000).toFixed(2)}초. 실제 청구서 금액은 확인하지 않았습니다.`;
    const random = data.matched_random;
    document.querySelector('#live-random').textContent = `같은 적용 수의 Matched Random 100회 평균: Pair 1회 대응 ${fmt(random['pair:1'].mean_ndcg10)}, 2회 대응 ${fmt(random['pair:2'].mean_ndcg10)}. 무작위 분포는 독립 평가의 신뢰구간이 아닙니다.`;
    const post = data.posthoc_unique_quote_grounding.arms;
    document.querySelector('#live-grounding').textContent = `별도 사후 진단: 원문에서 유일하게 일치한 인용문의 위치만 보정했습니다. 추가 모델 호출은 0회입니다. Rubric은 ${post['rubric:1'].apply_count}/${post['rubric:2'].apply_count}건 적용, nDCG@10 ${fmt(post['rubric:1'].metrics.overall.ndcg10)}/${fmt(post['rubric:2'].metrics.overall.ndcg10)}입니다. 원래 실험 결과를 대체하지 않으며 RulesPlus보다 낮습니다.`;
    const zero = data.posthoc_zero_hit_selection.arms['pair:1'];
    document.querySelector('#live-zero-hit').textContent = `별도 사후 선택 규칙: 원래 검색 결과가 0건일 때 의미 검증을 통과하고 결과를 만든 후보를 우선했습니다. 정답 접근·추가 호출 없이 Pair 두 반복 모두 nDCG@10 ${fmt(zero.metrics.overall.ndcg10)}, 정상 악화 ${zero.normal_regression_count}건입니다. RulesPlus 대비 우위는 없으며 독립 검증 전입니다.`;
    document.querySelector('#live-run').href = data.run_url;
    document.querySelector('#live-evidence').textContent = JSON.stringify({model:data.model_id, plan:data.plan_hash,
      input:data.input_hash, protocol:data.protocol_hash, assembly:data.assembly_hash,
      human_semantic_review:data.semantic_human_review_complete, independent_evaluation:data.independent_evaluation_complete},null,2);
    document.querySelector('#live-report').hidden = false;
    document.querySelector('#live-load').textContent = '실제 저장 응답의 집계입니다. 이 화면은 API를 호출하지 않습니다.';
    const privateResponse = await fetch('research-v5-live-details.json');
    if (!privateResponse.ok) return;
    const details = await privateResponse.json();
    if (details.assembly_hash !== data.assembly_hash) throw Error('상세 기록과 집계의 실행 해시가 다릅니다.');
    const queries = document.querySelector('#live-queries'); const conditions = document.querySelector('#live-condition');
    details.queries.forEach((q, index) => {const option=node('option',`${q.query} · 후보 ${q.candidates.length}개`); option.value=index; queries.append(option);});
    for (const name of Object.keys(names).filter(x=>x.includes(':'))) {const option=node('option',names[name]);option.value=name;conditions.append(option);}
    const show = () => {
      const q=details.queries[Number(queries.value)]; const trial=q.trials[conditions.value];
      const panel=document.querySelector('#live-detail');panel.replaceChildren();
      panel.append(node('h3',q.query),node('p',`수정 전 nDCG@10 ${fmt(q.before.metrics.ndcg10)} → 선택 적용 후 ${fmt(trial.metrics.ndcg10)}`),
        node('p',`수정 전 순위: ${q.before.ranking.join(' → ') || '결과 없음'}`),node('p',`적용 후 순위: ${trial.ranking.join(' → ') || '결과 없음'}`));
      if (!q.candidates.length) panel.append(node('p','이 질의에는 저장된 후보가 없습니다.'));
      q.candidates.forEach((candidate,index)=>{
        const decision=trial.decision.candidate_decisions[index]; const verdict=trial.verdicts[index]; const card=node('article','');
        card.append(node('h3',`후보 ${index+1} · ${trial.decision.candidate_index===index ? '적용' : '미선택/보류'}`),
          node('p',decision.errors.length ? decision.errors.map(x=>reasons[x] || x).join(' / ') : '형식·원문·해당 조건의 선택 기준 통과'),
          node('pre',JSON.stringify(candidate,null,2)));
        for (const assessment of verdict?.assessments || []) {
          card.append(node('p',`모델 판정: ${assessment.relation} · 보정되지 않은 confidence ${assessment.confidence}`),node('p',assessment.reasoning));
          for (const citation of assessment.citations) {
            const doc=q.documents.find(x=>x.doc_id===citation.doc_id);
            const valid=doc && Array.from(doc.text).slice(citation.start,citation.end).join('')===citation.quote;
            card.append(node('p',`인용 ${citation.doc_id} [${citation.start}, ${citation.end}): ${citation.quote}`),
              node('p',`${valid ? '위치 검증 통과' : '위치 검증 실패'} · 원문 문자열 존재: ${doc?.text.includes(citation.quote) ? '예' : '아니오'}`));
            if (doc) {const source=node('details','');source.append(node('summary','판정에 제공된 원문'),node('pre',doc.text));card.append(source);}
          }
        }
        card.append(node('p','독립 사람의 의미 정오 판정은 아직 없습니다. 검색 점수로 의미 정답을 대신하지 않습니다.'));
        panel.append(card);
      });
    };
    queries.addEventListener('change',show);conditions.addEventListener('change',show);
    document.querySelector('#live-query-section').hidden=false;
    document.querySelector('#live-private-notice').textContent='로컬 전용 상세 파일을 표시합니다. 이 파일은 GitHub 공개에서 제외됩니다.';
    show();
  } catch(error) {document.querySelector('#live-load').textContent=error.message;}
})();
