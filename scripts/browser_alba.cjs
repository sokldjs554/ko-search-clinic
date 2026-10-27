/* Offline browser checks. Live-route responses below are explicit test doubles. */
const {chromium}=require('playwright');
const fs=require('fs');const path=require('path');const cp=require('child_process');const assert=require('assert');
(async()=>{
 const root=path.resolve(__dirname,'..');const out=path.join(root,'docs/verification/alba-20261027/browser');fs.mkdirSync(out,{recursive:true});
 const server=cp.spawn('python',['-m','http.server','8765','--bind','127.0.0.1','--directory',path.join(root,'src/searchclinic')],{stdio:'ignore'});
 let browser;
 try{
  for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:8765/web/')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE||undefined,headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--no-zygote'],env:{...process.env,LD_LIBRARY_PATH:process.env.CHROME_LIBRARY_PATH||process.env.LD_LIBRARY_PATH||''}});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8765/web/');await page.locator('#cases button').first().waitFor();
  assert.equal(await page.locator('#cases button').count(),24);
  assert.match(await page.locator('#status').textContent(),/저장된 실제 실행/);
  // Capture measured success and a blocked result without mocking either report.
  await page.locator('#cases button').nth(6).click();assert.match(await page.locator('#gate-text').textContent(),/채택/);
  await page.screenshot({path:path.join(out,'desktop-replay.png')});
  await page.locator('#result').screenshot({path:path.join(out,'diagnosis-detail.png')});
  await page.locator('.sources').screenshot({path:path.join(out,'evidence-detail.png')});
  await page.locator('#cases button').first().click();assert.equal(await page.locator('#result-state').textContent(),'검증 실패');
  await page.screenshot({path:path.join(out,'desktop-blocked.png')});
  for(const width of [320,390,650]){
   await page.setViewportSize({width,height:844});await page.locator('#cases button').nth(6).click();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:path.join(out,`mobile-${width}.png`),fullPage:true});
   if(width===390){await page.locator("#result").scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,"mobile-detail.png")});await page.evaluate(()=>scrollTo(0,0));}
  }
  // Recorded API response used solely to test UI transitions, never as fresh generation evidence.
  const measured=JSON.parse(fs.readFileSync(path.join(root,'src/searchclinic/web/replay.json'),'utf8')).rows[6];
  const fixture={...measured,id:'test-only',mode:'live',gate:null};let delayed=false,fail=false,applies=0;
  await page.route('**/explanations',async route=>{if(delayed)await new Promise(r=>setTimeout(r,500));await route.fulfill({status:fail?502:200,contentType:'application/json',body:JSON.stringify(fail?{detail:'upstream_timeout'}:fixture)});});
  await page.route('**/explanations/test-only/apply',async route=>{applies++;await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...fixture,gate:measured.gate})});});
  await page.selectOption('#mode','live');await page.fill('#token','test-local-token-not-api-key');
  await page.click('#generate');await page.waitForFunction(()=>document.querySelector('#apply').disabled===false);
  await page.fill('#query','다른검색');assert(await page.locator('#result').isHidden());assert(await page.locator('#apply').isDisabled());assert.equal(applies,0);assert.equal(await page.locator('.document').count(),0);
  delayed=true;await page.click('#generate');assert(await page.locator('#query').isDisabled());await page.click('#cancel');await page.waitForFunction(()=>!document.querySelector('#generate').disabled);assert.match(await page.locator('#status').textContent(),/수신을 취소/);
  delayed=false;fail=true;await page.click('#generate');await page.waitForFunction(()=>!document.querySelector('#generate').disabled);assert.match(await page.locator('#status').textContent(),/upstream_timeout/);assert.equal(await page.locator('.document').count(),0);
  fail=false;await page.click('#generate');await page.waitForFunction(()=>!document.querySelector('#generate').disabled);await page.click('#apply');await page.waitForFunction(()=>document.querySelector('#gate-text').textContent.includes('채택'));assert.equal(applies,1);
  await page.selectOption('#mode','replay');assert.match(await page.locator('#status').textContent(),/저장된 실제 실행/);
  const download=page.waitForEvent('download');await page.click('#download');assert.equal((await download).suggestedFilename(),'search-review.json');
  assert.deepEqual(errors,[]);
  const result={passed:true,viewports:[1440,320,390,650],checks:['24 measured replay rows','accepted and blocked measured results','no horizontal overflow','stale input invalidation','pending input lock','cancel','provider error','gate application','mode switch','download','no page errors'],live_route:'test double; no paid API requests'};
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{if(browser)await browser.close();server.kill();}
})();
