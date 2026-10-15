/* Optional Telegram UX bridge; no login, token forwarding or automatic messages. */
const UUID=/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
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
export function incomingInvite(){
  const params=new URLSearchParams(location.search);
  const raw=params.get('invite')||params.get('tgWebAppStartParam')||params.get('startapp');
  let found=parseInvite(raw)||parseInvite(window.Telegram?.WebApp?.initDataUnsafe?.start_param);
  try{if(found)sessionStorage.setItem('qw-farm.incoming',found);else found=parseInvite(sessionStorage.getItem('qw-farm.incoming'));}catch{}
  return found;
}
export function clearInvite(){
  try{sessionStorage.removeItem('qw-farm.incoming');}catch{}
  try{const u=new URL(location.href);for(const key of ['invite','startapp','tgWebAppStartParam'])u.searchParams.delete(key);history.replaceState(null,'',u);}catch{}
}
export function openTelegram(link){
  const u=new URL(link);if(u.protocol!=='https:'||u.hostname!=='t.me')throw new Error('Недопустимая ссылка Telegram.');
  const tg=window.Telegram?.WebApp;
  if(tg?.initData&&typeof tg.openTelegramLink==='function')tg.openTelegramLink(link);
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
export function inTelegram(){return !!window.Telegram?.WebApp?.initData;}
export async function bootTelegram(onResize,onBack,force=false){
  const seemsTelegram=location.hash.includes('tgWebApp')||location.search.includes('tgWebApp')||window.Telegram?.WebApp?.initData;
  if(!seemsTelegram&&!force)return null;
  if(!window.Telegram?.WebApp){
    await new Promise(resolve=>{const script=document.createElement('script');script.src='https://telegram.org/js/telegram-web-app.js';script.async=true;script.onload=resolve;script.onerror=resolve;document.head.append(script);});
  }
  const tg=window.Telegram?.WebApp;if(!tg)return null;
  function syncViewport(kind,event){
    const stable=Number(tg.viewportStableHeight),current=Number(tg.viewportHeight);
    const valid=n=>Number.isFinite(n)&&n>0;
    // Telegram reports the visible WebView height; the shell applies its safe insets separately.
    const useCurrent=kind==='fullscreenChanged'||event?.isStateStable===false;
    const height=useCurrent&&valid(current)?current:valid(stable)?stable:current;
    if(valid(height))document.documentElement.style.setProperty('--app-height',`${height}px`);
    else document.documentElement.style.removeProperty('--app-height');
    for(const [prefix,inset]of [['safe',tg.safeAreaInset],['content',tg.contentSafeAreaInset]]){
      for(const edge of ['top','right','bottom','left'])document.documentElement.style.setProperty(`--tg-${prefix}-${edge}`,Math.max(0,Number(inset?.[edge])||0)+'px');
    }
    onResize?.();
  }
  try{tg.ready();tg.expand();tg.BackButton?.show();tg.BackButton?.onClick(onBack);
    for(const name of ['viewportChanged','safeAreaChanged','contentSafeAreaChanged','fullscreenChanged'])tg.onEvent?.(name,event=>syncViewport(name,event));
    syncViewport('initial');
  }catch{}
  try{if(tg.isVersionAtLeast?.('7.7'))tg.disableVerticalSwipes?.();}catch{}
  try{tg.setHeaderColor?.('#f6f5ed');tg.setBackgroundColor?.('#edf3e2');}catch{}
  return tg;
}
