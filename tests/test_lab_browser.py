"""Real isolated Chrome against the lab view. Fixture brains: no model calls."""
import os
import re

from playwright.async_api import async_playwright, expect

from exchange.client import PeerClient
from exchange.common import DATA, config, uid, write_json


async def test_lab_pause_inject_resume_replay_in_chrome(tmp_path, monkeypatch):
    c = config()
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    folder = DATA / 'receipts' / ('lab-browser-' + uid())
    folder.mkdir(parents=True)
    errors = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(str(tmp_path / 'chrome-profile'), channel='chrome', headless=True,
            viewport={'width': 1440, 'height': 1000}, env={**os.environ, 'TMPDIR': str(tmp_path)})
        try:
            await context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(c['peers']['observer']['url'] + '/') else route.abort())
            page = context.pages[0]
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(c['peers']['observer']['url'])
            await page.get_by_label('Operator token').fill(c['peers']['observer']['tokens']['operator'])
            await page.get_by_role('button', name='Connect', exact=True).click()
            await expect(page.locator('#lab')).to_be_visible()
            await expect(page.locator('#lab-approval-text')).to_contain_text('12 Claude CLI calls')
            # A live run cannot start without the explicit approval box.
            await page.locator('#lab-brain').select_option('claude')
            await expect(page.locator('#lab-start')).to_be_disabled()
            await page.locator('#lab-brain').select_option('fixture')
            await page.locator('#lab-mode').select_option('intervention')
            await page.locator('#lab-trial').select_option('random')
            await page.locator('#lab-start').click()
            await expect(page.locator('#lab-status')).to_contain_text('paused', timeout=30000)
            await expect(page.locator('#lab-source')).to_have_text('FIXTURE')
            await expect(page.locator('#lab-inputs-badge')).to_have_text('SIMULATED INPUTS')
            await expect(page.locator('#lab-step')).to_be_enabled()
            await page.locator('#lab-inspect').click()
            await expect(page.locator('#lab-records details')).to_have_count(3)
            await page.locator('#lab').screenshot(path=str(folder / 'paused.png'))
            await page.locator('#lab-inject-open').click()
            await page.locator('#inject-suggest').click()
            await page.locator('#inject-submit').click()
            await expect(page.locator('#lab-message')).to_contain_text('Injected heat_load')
            await page.locator('#lab-resume').click()
            await expect(page.locator('#lab-status')).to_contain_text('completed', timeout=60000)
            run_id = await page.locator('#lab-run').input_value()
            body = (await PeerClient(c, 'operator').http('observer', 'GET', f'/lab/runs/{run_id}')).json()
            delivered = body['run']['results']['messages']['delivered']
            # The transcript shows exactly the recorded deliveries, and the memories show the revision history.
            await expect(page.locator('#lab-transcript .k-message')).to_have_count(delivered)
            await expect(page.locator('#home-physics .lab-fact.superseded')).to_have_count(2)
            await expect(page.locator('#home-mathematics .st-corrected').first).to_be_visible()
            await expect(page.locator('#home-physics .lab-verdict')).to_have_text('✓ matches ground truth')
            await page.locator('#home-mathematics .lab-fact-btn').last.click()
            assert await page.locator('#lab-lineage .lab-hop').count() >= 4
            await expect(page.locator('#lab-lineage')).to_contain_text('operator injection')
            await expect(page.locator('#lab-results .lab-prop')).to_contain_text('into A · Physics only')
            await page.locator('#lab').screenshot(path=str(folder / 'completed.png'))
            # Isolated baseline on the same inputs appears beside the run.
            await page.locator('#lab-baseline').click()
            await expect(page.locator('#lab-status')).to_contain_text('A · Isolated baseline · completed', timeout=30000)
            await expect(page.locator('#lab-results .lab-table tr').first.locator('th')).to_have_count(3)
            await page.locator('#lab-run').select_option(run_id)
            await expect(page.locator('#lab-source')).to_have_text('FIXTURE')
            await page.locator('#lab-replay').click()
            await expect(page.locator('#lab-source')).to_have_text('REPLAY')
            await expect(page.locator('#lab-message')).to_contain_text('Replay finished', timeout=60000)
            await expect(page.locator('#lab-transcript .k-message')).to_have_count(delivered)
            await page.set_viewport_size({'width': 390, 'height': 844})
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            await page.locator('#lab').screenshot(path=str(folder / 'mobile.png'))
            assert not errors, errors
            write_json(folder / 'receipt.json', {'browser': 'installed Google Chrome, isolated headless profile', 'run_id': run_id,
                'delivered_messages': delivered, 'transcript_matches_recorded_deliveries': True, 'pause_inject_resume': True,
                'replay_labelled': True, 'baseline_compared': True, 'mobile_overflow': False, 'models_invoked': False})
        finally:
            await context.close()
