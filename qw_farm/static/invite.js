/* Farm invitation links and sharing helpers. The Telegram bridge (SDK, safe-area, fullscreen, BackButton) lives in the shared shell: /app/shell/qw-shell.js (window.QW). */
const UUID=/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
const SHARE_TOKEN=/^[A-Za-z0-9_-]{43}$/;
export function parseInvite(input){
  if(typeof input!=='string'||input.length>2048)return null;
  let value=input.trim();
  if(value.startsWith('farm_'))value=value.slice(5);
  if(UUID.test(value))return value.toLowerCase();
  try{const u=new URL(value);if(!['http:','https:'].includes(u.protocol))return null;
    const raw=u.searchParams.get('invite')||u.searchParams.get('startapp')||u.searchParams.get('tgWebAppStartParam');
    if(!raw)return null;return parseInvite(raw);
  }catch{return null;}
}
// Shared links carry a one-use secret. A bare farm UUID is still accepted for
// older links and manual requests, but it never authorizes immediate joining.
export function parseInviteHint(input){
  if(typeof input!=='string'||input.length>2048)return null;
  let value=input.trim();
  if(value.startsWith('farm_'))value=value.slice(5);
  if(SHARE_TOKEN.test(value))return value;
  if(UUID.test(value))return value.toLowerCase();
  try{const u=new URL(value);if(!['http:','https:'].includes(u.protocol))return null;
    return parseInviteHint(u.searchParams.get('invite')||u.searchParams.get('startapp')||u.searchParams.get('tgWebAppStartParam')||'');
  }catch{return null;}
}
export function incomingInvite(){
  const params=new URLSearchParams(location.search);
  const raw=params.get('invite')||params.get('tgWebAppStartParam')||params.get('startapp');
  let found=parseInviteHint(raw)||parseInviteHint(window.Telegram?.WebApp?.initDataUnsafe?.start_param);
  try{if(found)sessionStorage.setItem('qw-farm.incoming',found);else found=parseInviteHint(sessionStorage.getItem('qw-farm.incoming'));}catch{}
  return found;
}
export function clearInvite(){
  try{sessionStorage.removeItem('qw-farm.incoming');}catch{}
  try{const u=new URL(location.href);for(const key of ['invite','startapp','tgWebAppStartParam'])u.searchParams.delete(key);history.replaceState(null,'',u);}catch{}
}
export function openTelegram(link){
  const u=new URL(link);if(u.protocol!=='https:'||u.hostname!=='t.me')throw new Error('Недопустимая ссылка Telegram.');
  const tg=window.Telegram?.WebApp;
  // Same Telegram check as the shell (QW.tg): after /app → /app/farm the SDK may lose initData, and window.open is a silent no-op in Telegram Desktop.
  if((tg?.initData||window.QW?.tg)&&typeof tg?.openTelegramLink==='function')tg.openTelegramLink(link);
  else window.open(link,'_blank','noopener,noreferrer');
}
export function shareData(info){
  const url=info?.mini_app_url||info?.web_url||'';
  const farmName=typeof info?.farm_name==='string'&&info.farm_name.trim()?` «${info.farm_name.trim()}»`:'';
  return {title:'Приглашение на ферму',text:`Приглашаю тебя на ферму${farmName} в QuizzyWizzy! 🌱\nОткрой ссылку и подтверди приглашение в игре.`,url};
}
export function mailtoUrl(info){
  const d=shareData(info);d.url=info?.web_url||d.url;
  return 'mailto:?subject='+encodeURIComponent(d.title)+'&body='+encodeURIComponent(d.text+(d.url?'\n'+d.url:''));
}
/* System share sheet (WhatsApp, VK, mail ...). Falls back to copying the link. Returns 'shared' | 'copied' | 'cancelled' | 'failed'. */
export async function shareLink(info,copy){
  const d=shareData(info);
  if(!d.url&&!d.text)return 'failed';
  if(d.url&&typeof navigator!=='undefined'&&typeof navigator.share==='function'){
    try{await navigator.share(d);return 'shared';}catch(e){if(e&&e.name==='AbortError')return 'cancelled';}
  }
  try{await copy(d.url||(d.text));return 'copied';}catch{return 'failed';}
}
