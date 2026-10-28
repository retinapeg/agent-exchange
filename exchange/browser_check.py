"""Read-only browser evidence against the already-running demonstration."""
import json
import os

from playwright.async_api import async_playwright, expect

from exchange.common import ROOT, DATA, config, uid, write_json


async def browser_check():
    c=config(); origin=c['peers']['observer']['url']
    folder=DATA/'receipts'/('browser-live-'+uid());folder.mkdir(parents=True)
    temporary=ROOT/'.cache/browser'/uid(); temporary.mkdir(parents=True)
    errors=[]
    async with async_playwright() as p:
        context=await p.chromium.launch_persistent_context(str(temporary/'profile'),channel='chrome',headless=True,
            viewport={'width':1440,'height':1000},env={**os.environ,'TMPDIR':str(temporary)})
        try:
            await context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
            page=context.pages[0];page.on('pageerror',lambda e:errors.append(str(e)))
            await page.goto(origin.rstrip('/') + '/admin')
            await page.get_by_label('Operator token').fill(c['peers']['observer']['tokens']['operator'])
            await page.get_by_role('button',name='Connect',exact=True).click()
            await expect(page.locator('#workspace')).to_be_visible()
            await expect(page.locator('.agent')).to_have_count(3)
            await expect(page.locator('#token')).to_have_value('')
            await page.screenshot(path=str(folder/'desktop.png'),full_page=True)
            live=DATA/'showcases/v1-live/results.json'
            run_id=None
            if live.exists():
                run_id=json.loads(live.read_text())['results'][-1]['run_id']
                run=page.locator(f'[data-run-id="{run_id}"]')
                await run.locator('summary').first.click()
                await expect(run.locator('.run-status')).to_have_text('verified')
                await run.screenshot(path=str(folder/'live-artifact.png'))
                await run.get_by_role('button',name='Show trace').click()
                await page.locator('#timeline').screenshot(path=str(folder/'live-trace.png'))
            await page.locator('#models').screenshot(path=str(folder/'model-usage.png'))
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            await page.screenshot(path=str(folder/'mobile.png'),full_page=True)
            assert not errors
            result={'browser':'installed Chrome; isolated profile','real_http':True,'headless':True,
                'desktop':[1440,1000],'mobile':[390,844],'page_errors':errors,'live_run_visible':run_id,
                'model_calls_started':0,'new_service_payments':0,'horizontal_overflow':False}
            write_json(folder/'receipt.json',result)
            await page.get_by_role('button',name='Lock',exact=True).click()
            return {**result,'directory':str(folder.relative_to(ROOT))}
        finally: await context.close()
