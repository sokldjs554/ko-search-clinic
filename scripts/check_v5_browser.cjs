const {chromium}=require('playwright');
const path=require('node:path');const fs=require('node:fs');
const output=process.argv[2] || 'work/browser';fs.mkdirSync(output,{recursive:true});
const base=process.argv[3] || 'http://127.0.0.1:8765';
(async()=>{
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
if(process.argv.includes('--public'))await page.route('**/research-replay.json',route=>route.fulfill({status:404,body:''}));
await page.goto(base+'/research.html');await page.waitForSelector('#report:not([hidden])');
if(await page.locator('#summary tr').count()!==3)throw Error('summary coverage');
const count=await page.locator('#queries option').count();if(count!==(process.argv.includes('--public')?0:36))throw Error('query coverage');
for(let i=0;i<count;i++){await page.selectOption('#queries',String(i));if(!(await page.locator('#detail h2').first().textContent()))throw Error('missing query');}
if(count)await page.selectOption('#queries','20');await page.screenshot({path:path.join(output,'research-desktop.png'),fullPage:true});
for(const width of [320,390]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('horizontal overflow '+width);}
await page.screenshot({path:path.join(output,'research-mobile.png'),fullPage:true});
await page.goto(base+'/');await page.waitForSelector('#cases button');if(!(await page.locator('a[href="research.html"]').count()))throw Error('research navigation');
if(errors.length)throw Error(errors.join('\n'));console.log(JSON.stringify({research_queries:count,summary_arms:3,viewports:[1440,320,390],rag_replay_loaded:true,page_errors:errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
