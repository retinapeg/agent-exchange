'use strict';
const $ = id => document.getElementById(id);
const screens = ['auth-screen','profile-screen','waiting-screen','matched-screen','compatibility-screen'];
let loginMode = false;
let currentPreview = null;
let lastState = null;
let poll = null;
let lastDraftKey = null;
const PROMPT = `Draft a SHORT, non-sensitive profile to help me find one compatible person for a project or collaboration. Use only information I already shared with you. Do not fabricate details. Do not include raw chat logs, mental or physical health, politics, relationships, religion, home address, phone, salary, employer, school, or private identifiers. Return only valid JSON with exactly these six keys: {"interests": [1-8 short tags], "goals": [1-8 short tags], "offers": [0-8 skills I offer], "seeks": [0-8 skills I want in a collaborator], "style": "collaborative|async|structured|exploratory|flexible", "timezone": "Europe/London"}. If uncertain, prefer a short accurate list. I will review and approve every field before sharing.`;
function flash(text, error=false){const e=$('flash');e.textContent=text;e.classList.toggle('error',error);e.hidden=false;window.scrollTo({top:0,behavior:'smooth'});}
async function api(path, method='GET', data=null){const options={method,credentials:'same-origin',headers:{}};if(data!==null){options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}const r=await fetch(path,options);let body={};try{body=await r.json()}catch{}if(!r.ok)throw new Error(typeof body.detail==='string'?body.detail:`Request failed (${r.status})`);return body}
function show(id){for(const name of screens)$(name).hidden=name!==id;$('account-screen').hidden=id==='auth-screen';if(id==='auth-screen')$('logout').hidden=true;else $('logout').hidden=false;}
function setAuthMode(mode){loginMode=mode;$('name-label').hidden=mode;$('name').required=!mode;$('password-hint').hidden=mode;$('password').autocomplete=mode?'current-password':'new-password';$('auth-submit').textContent=mode?'Sign in':'Create my account';$('register-tab').classList.toggle('selected',!mode);$('login-tab').classList.toggle('selected',mode)}
function tags(id){return $(id).value.split(',').map(x=>x.trim()).filter(Boolean)}
function formProfile(){return {interests:tags('interests'),goals:tags('goals'),offers:tags('offers'),seeks:tags('seeks'),style:$('style').value,timezone:$('timezone').value}}
function approvedFields(){return [...$('approve-fields').querySelectorAll('input')].filter(x=>x.checked).map(x=>x.value)}
function fillProfile(p){for(const id of ['interests','goals','offers','seeks'])$(id).value=(p[id]||[]).join(', ');$('style').value=p.style||'collaborative';$('timezone').value=p.timezone||'Europe/London';$('preview').hidden=true;currentPreview=null;}
function fillList(id, values, empty='No additional details were disclosed.') {
  const list = $(id);
  list.replaceChildren();
  for (const value of values?.length ? values : [empty]) {
    const li = document.createElement('li');
    li.textContent = value;
    list.append(li);
  }
}
function renderStatus(s) {
  const oldMatch = lastState?.match?.id;
  lastState = s;
  $('flash').hidden = true;
  if (s.contact) {
    // Do not overwrite a contact form while somebody is typing in it.
    if (document.activeElement !== $('edit-linkedin-url')) $('edit-linkedin-url').value = s.contact.linkedin_url || '';
    if (document.activeElement !== $('linkedin-url')) $('linkedin-url').value = s.contact.linkedin_url || '';
    $('edit-share-linkedin').checked = !!s.contact.share_linkedin_on_match;
    $('share-linkedin').checked = !!s.contact.share_linkedin_on_match;
  }
  if (!s.joined) {
    show('profile-screen');
    if (s.draft) {
      const key = JSON.stringify([s.draft, s.draft_fields]);
      if (key !== lastDraftKey) {
        lastDraftKey = key;
        fillProfile(s.draft);
        for (const box of $('approve-fields').querySelectorAll('input')) {
          if (!box.disabled) box.checked = (s.draft_fields || []).includes(box.value);
        }
        previewCurrent().catch(err => flash(err.message, true));
      }
    }
    return;
  }
  if (s.match) {
    show('matched-screen');
    const m = s.match;
    $('partner').textContent = m.partner_name;
    $('score').textContent = m.score;
    $('match-state').textContent = m.state === 'accepted' ?
      'You both agreed to connect.' : m.my_accepted ?
      'You accepted. Waiting for their response.' :
      'You have a compatible partner. Choose whether to connect.';
    fillList('explanations', m.explanation?.reasons);
    fillList('match-ideas', m.explanation?.project_ideas);
    $('match-actions').hidden = m.my_accepted || m.state === 'accepted';
    $('linkedin-card').hidden = !m.partner_linkedin;
    if (m.partner_linkedin) $('partner-linkedin').href = m.partner_linkedin;
    $('contact-card').hidden = m.state !== 'accepted';
    $('contact-info').textContent = m.partner_email ?
      `Email ${m.partner_name}: ${m.partner_email}` : '';
    if (m.id !== oldMatch) {
      document.title = 'YOU\'VE GOT A MATCH! | Agent Exchange';
      flash(`YOU'VE GOT A MATCH! Meet ${m.partner_name}. Your score is ${m.score}/100.`);
    }
    return;
  }
  document.title = 'Agent Exchange | Find your person to build with';
  if (s.compatibility_preview) {
    show('compatibility-screen');
    const p = s.compatibility_preview;
    $('preview-score').textContent = p.score;
    $('preview-person').textContent = `Compatibility with ${p.partner_name}`;
    fillList('preview-reasons', p.explanation?.reasons);
    fillList('preview-ideas', p.explanation?.project_ideas);
    return;
  }
  show('waiting-screen');
  const waiting = s.waiting_count;
  $('waiting-heading').textContent = 'You are in the pool.';
  $('waiting-text').textContent = waiting < 2 ?
    'Your agent context is ready. Once another person joins, compatibility checks begin.' :
    'We are checking eligible pairings and will update this page automatically.';
  $('pool-progress').style.width = `${Math.min(100, 100 * waiting / 2)}%`;
  $('pool-caption').textContent = `${waiting} available · matches start with 2 people · score threshold ${s.threshold}/100`;
}
async function refresh(){try{const s=await api('/api/me');renderStatus(s)}catch(e){if(String(e).includes('Sign in')||String(e).includes('Session expired')){show('auth-screen');return}flash(e.message,true)}}
async function loadPublic(){try{const d=await api('/api/public');$('members').textContent=`${d.participants} in the network`;$('cohort-stat').textContent=`${d.minimum_cohort}+`;$('threshold-stat').textContent=d.threshold;if(d.demo){$('mode-flag').hidden=false;const view=await api('/api/demo/overview');renderDemo(view)}}catch(e){flash(e.message,true)}}
function renderDemo(view){$('demo-screen').hidden=false;const stats=$('demo-stats');stats.replaceChildren();for(const v of [`${view.participants.length} synthetic participants`,`${view.matches.length} exclusive matches`,`${view.threshold}/100 threshold`]){const span=document.createElement('span');span.textContent=v;stats.append(span)}const target=$('demo-matches');target.replaceChildren();for(const m of view.matches){const card=document.createElement('div');card.className='demo-match';const names=document.createElement('span');names.textContent=`${m.first} + ${m.second}`;const score=document.createElement('strong');score.textContent=`${m.score}/100`;card.append(names,score);target.append(card)}}
$('register-tab').addEventListener('click',()=>setAuthMode(false));$('login-tab').addEventListener('click',()=>setAuthMode(true));
$('auth-form').addEventListener('submit',async e=>{e.preventDefault();try{const d={email:$('email').value,password:$('password').value};if(!loginMode)d.name=$('name').value;await api(loginMode?'/api/login':'/api/register','POST',d);await refresh()}catch(err){flash(err.message,true)}});
$('logout').addEventListener('click',async()=>{try{await api('/api/logout','POST');show('auth-screen')}catch(e){flash(e.message,true)}});
$('copy-prompt').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(PROMPT);flash('Prompt copied. Ask your AI assistant, then review the JSON draft here.')}catch{flash('Clipboard unavailable. Use the JSON import and manual fields instead.',true)}});
async function previewCurrent() {
  const data = {profile:formProfile(),approved_fields:approvedFields()};
  const preview = await api('/api/preview','POST',data);
  currentPreview = data;
  $('preview-json').textContent = JSON.stringify(preview.shared,null,2);
  $('preview').hidden = false;
  $('consent').checked = false;
  $('join-pool').disabled = true;
  $('preview').scrollIntoView({behavior:'smooth',block:'center'});
}
$('import-json').addEventListener('click',async()=>{
  try {
    const raw = $('json-draft').value.trim().replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/,'').trim();
    const p = JSON.parse(raw);
    const required=['interests','goals','offers','seeks','style','timezone'];
    if(required.some(x=>!(x in p))||Object.keys(p).length!==6)throw new Error('The AI response should contain only the six matching fields');
    for(const id of ['interests','goals','offers','seeks']) if(!Array.isArray(p[id])) throw new Error(`${id} must be a list`);
    fillProfile(p);
    await previewCurrent();
  } catch(e) {flash('Could not review your AI summary: '+e.message,true)}
});
$('profile-form').addEventListener('submit',async e=>{e.preventDefault();try{await previewCurrent()}catch(err){flash(err.message,true)}});
$('consent').addEventListener('change',()=>{$('join-pool').disabled=!$('consent').checked});
$('join-pool').addEventListener('click',async()=>{try{
  if(!currentPreview||!$('consent').checked)throw new Error('Review and approve the context first');
  await api('/api/contact','POST',{linkedin_url:$('linkedin-url').value.trim(),share_on_match:$('share-linkedin').checked});
  await api('/api/profile','POST',{...currentPreview,consent:true});
  await refresh();await loadPublic();
}catch(e){flash(e.message,true)}});
$('refresh').addEventListener('click',refresh);
$('preview-refresh').addEventListener('click',refresh);
$('join-cta').addEventListener('click',()=>{
  const target = lastState?.joined ? (lastState.match ? 'matched-screen' : lastState.compatibility_preview ? 'compatibility-screen' : 'waiting-screen')
    : lastState ? 'profile-screen' : 'auth-screen';
  $(target).scrollIntoView({behavior:'smooth',block:'start'});
});
$('save-linkedin').addEventListener('click',async()=>{try{
  await api('/api/contact','POST', {linkedin_url:$('edit-linkedin-url').value.trim(),share_on_match:$('edit-share-linkedin').checked});
  flash('Contact preference saved. Your LinkedIn is shown only when you authorise sharing.');
}catch(e){flash(e.message,true)}});
for(const decision of ['accept','decline'])$(decision).addEventListener('click',async()=>{try{if(decision==='decline'&&!confirm('Decline this match and return to the waiting pool?'))return;await api('/api/decision','POST',{decision});await refresh()}catch(e){flash(e.message,true)}});
$('make-token').addEventListener('click',async()=>{try{const d=await api('/api/tokens','POST');$('token-output').textContent=d.token;$('token-output').hidden=false;flash('MCP token created. Copy it now; it will not be shown again.')}catch(e){flash(e.message,true)}});
$('revoke-tokens').addEventListener('click',async()=>{try{await api('/api/tokens','DELETE');$('token-output').hidden=true;flash('All your MCP tokens have been revoked.')}catch(e){flash(e.message,true)}});
$('delete-account').addEventListener('click',async()=>{if(!confirm('Permanently delete your account and matching profile? Your current match will be cancelled.'))return;try{await api('/api/account','DELETE');show('auth-screen');flash('Account and profile deleted. Previously revealed contact details cannot be recalled.')}catch(e){flash(e.message,true)}});
(async function init(){setAuthMode(false);await loadPublic();await refresh();poll=setInterval(async()=>{if(lastState?.joined)await refresh()},5000)})();
