/* Sidebar membership is static HTML; scrollspy changes selection only. */
let navigationTarget=null,navigationDestination=0,spyFrame=0,sectionBoundaries=[];
function navigationOffset(){return document.querySelector('.topbar').getBoundingClientRect().height+18;}
function setActiveSection(name){
  if(!routes[name])return;
  document.querySelectorAll('.sidebar nav a').forEach(a=>{
    const active=a.hash==='#'+(['modeling','validation','calculating'].includes(name)?'scenarios':name);
    a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
  });
  $('breadcrumb-current').textContent=routes[name][1];
  if(state.step>=4)$('page-title').textContent=routes[name][1];
  if(location.hash!=='#'+name)history.replaceState(null,'','#'+name);
}
function visibleSections(){return [...document.querySelectorAll('[data-nav-section]')].filter(el=>el.getClientRects().length);}
function syncNavigation(){
  if(navigationTarget){if(Math.abs(scrollY-navigationDestination)>2)return;navigationTarget=null;}
  if(!sectionBoundaries.length)return;
  const line=scrollY+2;let section=sectionBoundaries[0];
  for(const entry of sectionBoundaries){if(entry.activation<=line)section=entry;else break;}
  if(scrollY>0&&innerHeight+scrollY>=document.documentElement.scrollHeight-3)section=sectionBoundaries.at(-1);
  if(location.hash!=='#'+section.name)setActiveSection(section.name);
}
function scheduleNavigation(){if(!spyFrame)spyFrame=requestAnimationFrame(()=>{spyFrame=0;syncNavigation();});}
function observeNavigation(){
  const offset=navigationOffset(),max=Math.max(0,document.documentElement.scrollHeight-innerHeight);
  sectionBoundaries=visibleSections().map(el=>({name:el.dataset.navSection,top:scrollY+el.getBoundingClientRect().top}));
  sectionBoundaries.forEach(e=>e.activation=Math.max(0,e.top-offset));
  // Short final sections cannot reach the header. Distribute their boundaries over
  // the remaining scroll distance, preserving order in both directions.
  if(sectionBoundaries.at(-1)?.activation>max){
    const first=sectionBoundaries.findIndex(e=>e.activation>max),anchor=Math.max(0,first-2);
    const start=Math.min(max,sectionBoundaries[anchor].activation),end=sectionBoundaries.at(-1).activation;
    sectionBoundaries.slice(anchor).forEach(e=>{e.activation=start+(e.activation-start)*(max-start)/(end-start||1);});
  }
}
function scrollToSection(name){
  const target=document.querySelector(`[data-nav-section="${name}"]`)||$(name);if(!target)return;
  navigationTarget=name;setActiveSection(name);
  observeNavigation();
  navigationDestination=sectionBoundaries.find(e=>e.name===name)?.activation??Math.max(0,scrollY+target.getBoundingClientRect().top-navigationOffset());
  window.scrollTo({top:navigationDestination,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});scheduleNavigation();
}
// No narrow observer band: every boundary crossing is checked, at most once per frame.
// Cached document coordinates avoid measuring layout on each scroll event.
window.addEventListener('scroll',scheduleNavigation,{passive:true});
window.addEventListener('scrollend',()=>{navigationTarget=null;scheduleNavigation();});
window.addEventListener('resize',()=>{observeNavigation();scheduleNavigation();});
for(const type of ['wheel','touchstart','pointerdown'])window.addEventListener(type,()=>{navigationTarget=null;},{passive:true});
window.addEventListener('keydown',e=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(e.key))navigationTarget=null;});
document.addEventListener('toggle',()=>{observeNavigation();scheduleNavigation();},true);
new ResizeObserver(()=>{observeNavigation();scheduleNavigation();}).observe(document.querySelector('main'));
