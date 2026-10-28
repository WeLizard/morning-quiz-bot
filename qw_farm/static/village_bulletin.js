// Read-only village news from the farm projection. Missing sources produce no invented news.
import {statusText} from './merchant.js';
import {bannerText} from './festivals.js';
import {siteLabel} from './construction.js';

export function entries(me,now){
 const news=[],merchant=me?.merchant_view,festival=me?.festival;
 if(merchant&&(merchant.active===true||Number(merchant.next_at)>0))news.push({id:'merchant',title:'Вести от Сороки',source:'Сорока-коробейница',text:merchant.active===true?`Сорока на площади. ${statusText(merchant,now)}.`:`${statusText(merchant,now)}.`});
 const holiday=festival&&(festival.current||festival.upcoming?.soon)?festival.current?.phase==='fair'&&festival.fair?.todo?`${festival.current.name}: деревня отмечает праздник.`:bannerText(festival):'';
 if(holiday)news.push({id:'festival',title:'Праздник в деревне',source:festival.current?.host||'Агата',text:holiday});
 for(const project of me?.village_build?.projects||[]){
  if(!project.name||!['collecting','working','done'].includes(project.status))continue;
  news.push({id:`build:${project.id}`,title:project.name,source:'Механик Крот',text:siteLabel(project,project.name,now)});
 }
 return news;
}

export function renderBulletin(parent,me,now,h){
 h.note('Почтальон Ёж собрал свежие вести с площади.',parent);
 const news=entries(me,now),list=h.el('div',null,'village-bulletin');
 list.setAttribute('aria-label','Деревенские вести');
 for(const item of news){
  const c=h.card(item.title,item.source,'journal');c.classList.add('village-bulletin-entry');c.dataset.bulletinEntry=item.id;
  c.append(h.el('p',item.text,'note'));list.append(c);
 }
 if(!news.length)h.note('Свежих вестей пока нет. Загляни позже.',list);
 parent.append(list);
}
