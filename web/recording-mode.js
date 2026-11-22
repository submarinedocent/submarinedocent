/**
 * Recording mode: hides the "Work in progress" banner for screen recordings.
 *
 * Open any page with ?recording=1 and the banner is hidden on it and on every
 * later page in the same browser tab (sessionStorage, so it ends when the tab
 * closes).  ?recording=0 turns it back off.  Visitors without the parameter see
 * no change.  Load in <head> so the banner never draws first.
 */
(() => {
  const KEY = 'subdocent_recording';
  try {
    const flag = new URLSearchParams(location.search).get('recording');
    if (flag === '1') sessionStorage.setItem(KEY, '1');
    else if (flag === '0') sessionStorage.removeItem(KEY);
    if (sessionStorage.getItem(KEY) !== '1') return;
  } catch (e) {
    return;  // storage blocked: behave as a normal visit
  }
  const style = document.createElement('style');
  style.textContent = '.site-warning { display: none !important; }';
  document.head.appendChild(style);
})();
