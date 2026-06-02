// Adds a "Copy" button to every fenced code block on the docs site.
// Hooks `div.highlighter-rouge` (the Rouge block wrapper). Inline code is a
// bare <code> with the same class, so the `div.` qualifier excludes it.
(function () {
  function codeText(block) {
    var code = block.querySelector('pre code') || block.querySelector('pre');
    var text = code ? code.innerText : block.innerText;
    return text.replace(/\n+$/, '');
  }

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
    } catch (e) {
      /* no-op */
    }
    document.body.removeChild(ta);
  }

  function attach(block) {
    if (block.dataset.copyAttached) return;
    block.dataset.copyAttached = 'true';

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-code-button';
    btn.textContent = 'Copy';
    btn.setAttribute('aria-label', 'Copy code to clipboard');

    var resetTimer;
    btn.addEventListener('click', function () {
      var text = codeText(block);
      var markCopied = function () {
        btn.textContent = 'Copied';
        btn.classList.add('is-copied');
        clearTimeout(resetTimer);
        resetTimer = setTimeout(function () {
          btn.textContent = 'Copy';
          btn.classList.remove('is-copied');
        }, 2000);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(markCopied, function () {
          fallbackCopy(text);
          markCopied();
        });
      } else {
        fallbackCopy(text);
        markCopied();
      }
    });

    block.appendChild(btn);
  }

  function init() {
    var blocks = document.querySelectorAll('div.highlighter-rouge');
    Array.prototype.forEach.call(blocks, attach);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
