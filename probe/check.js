const { chromium } = require('./node_modules/playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 1200 } });
  const errs = []; p.on('pageerror', e => errs.push('pageerror: ' + e.message + '\n' + e.stack)); p.on('console', m => m.type() === 'error' && errs.push('console: ' + m.text()));
  await p.goto('http://localhost:8765/en.html'); await p.waitForTimeout(5000);
  console.log('status rows', await p.$$eval('#t-status tbody tr', t => t.length), 'reg rows', await p.$$eval('#t-reg tbody tr', t => t.length));
  console.log('note', await p.$eval('#note-status', e => e.innerText));
  await p.fill('#q', 'Sokcho').catch(() => {}); await p.waitForTimeout(300);
  console.log(await p.$$eval('#t-status tbody tr', t => t.map(x => x.innerText.replace(/\t/g, ' | ')).join('\n')).catch(e => e.message));
  console.log('errors', errs.join('\n'));
  await b.close();
})();
