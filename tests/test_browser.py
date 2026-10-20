"""Actual isolated Chrome smoke; credentials are never included in screenshots/receipts."""
from pathlib import Path
import os

from playwright.async_api import async_playwright, expect

from exchange.common import ROOT, DATA, config, uid, write_json
from exchange.client import PeerClient


async def test_actual_desktop_mobile_dashboard(tmp_path, monkeypatch):
    c = config()
    await PeerClient(c, 'operator').http('registry','POST','/refresh')
    monkeypatch.setenv('TMPDIR',str(tmp_path))
    folder = DATA / 'receipts' / ('browser-' + uid())
    folder.mkdir(parents=True)
    errors, forbidden = [], []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(str(tmp_path/'chrome-profile'), channel='chrome', headless=True,
            viewport={'width':1440,'height':1000}, env={**os.environ,'TMPDIR':str(tmp_path)})
        try:
            await context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(c['peers']['observer']['url'] + '/') else route.abort())
            page = context.pages[0]
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(c['peers']['observer']['url'])
            await expect(page.locator('#login')).to_be_visible()
            await page.get_by_label('Operator token').fill(c['peers']['observer']['tokens']['operator'])
            await page.get_by_role('button',name='Connect',exact=True).click()
            await expect(page.locator('#workspace')).to_be_visible()
            await expect(page.locator('.agent')).to_have_count(3)
            await expect(page.locator('#token')).to_have_value('')
            # Exercise the actual operator path: preview, bilateral HTTP approval
            # adapter, paid A2A task and independent acceptance. No CLI model calls.
            await page.locator('#task-policy').select_option('cheapest')
            await page.locator('#task-payment').select_option('simulator')
            await page.get_by_role('button',name='Submit task',exact=True).click()
            await expect(page.locator('#submission-status')).to_contain_text('accepted')
            import re
            run_id=re.search(r'Run ([a-f0-9-]+) accepted',await page.locator('#submission-status').inner_text()).group(1)
            approval=page.locator(f'[data-approval-id="{run_id}"]')
            await expect(approval).to_be_visible(timeout=15000)
            await expect(approval.locator('h3')).to_have_text('3 CREDIT → csv')
            await approval.locator('summary').click()
            await page.screenshot(path=str(folder/'approval.png'),full_page=True)
            await approval.get_by_role('button',name='Approve simulated payment').click()
            run=page.locator(f'[data-run-id="{run_id}"]')
            await expect(run.locator('.run-status')).to_have_text('verified',timeout=15000)
            await run.locator('summary').first.click()
            await expect(run.locator('.decision-table tr')).to_have_count(4)
            # A repeat click must retain the original operation even after refresh.
            await page.get_by_role('button',name='Submit task',exact=True).click()
            await expect(page.locator('#submission-status')).to_contain_text(run_id)
            await page.get_by_role('button',name='Refresh now').click()
            await expect(run).to_have_attribute('open','')
            await page.locator('#task-service').select_option('csv-audit')
            await page.get_by_role('button',name='Load example',exact=True).click()
            await page.locator('#task-payment').select_option('free')
            await page.locator('#task-provider').select_option('csv')
            await page.get_by_role('button',name='Submit task',exact=True).click()
            await expect(page.locator('#submission-status')).not_to_contain_text(run_id)
            await expect(page.locator('#submission-status')).to_contain_text('accepted')
            csv_id=re.search(r'Run ([a-f0-9-]+) accepted',await page.locator('#submission-status').inner_text()).group(1)
            await expect(page.locator(f'[data-run-id="{csv_id}"] .run-status')).to_have_text('verified',timeout=15000)
            await page.screenshot(path=str(folder/'desktop.png'),full_page=True)
            await page.locator('#run-list details').first.locator('summary').first.click()
            await expect(page.locator('#run-list details').first.locator('.details-grid')).to_be_visible()
            await page.screenshot(path=str(folder/'artifact.png'),full_page=True)
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            await page.screenshot(path=str(folder/'mobile.png'),full_page=True)
            await page.get_by_role('button',name='Lock',exact=True).click()
            await expect(page.locator('#login')).to_be_visible()
            assert (await context.request.get(c['peers']['observer']['url']+'/snapshot')).status == 401
            assert not errors
            write_json(folder/'receipt.json',{'browser':'installed Google Chrome in isolated headless profile','desktop':[1440,1000],'mobile':[390,844],
                'authenticated_live_data':True,'provider_cards':3,'artifact_expansion':True,'horizontal_overflow':False,'logout_revokes_session':True,'page_errors':errors})
            write_json(folder/'workflow.json',{'paid_run_id':run_id,'free_csv_run_id':csv_id,'real_http':True,'models_invoked':False,
                'exact_quote_approval':True,'deduplicated_submission':True,'expanded_state_retained':True,'both_verified':True})
        finally:
            await context.close()
