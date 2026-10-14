    // Interacciones y navegación accesible editorial v2
    (function initEditorialInteractions() {
      var anchorLinks = document.querySelectorAll('a[href^="#"]');
      for (var i = 0; i < anchorLinks.length; i++) {
        anchorLinks[i].addEventListener('click', function(e) {
          var targetId = this.getAttribute('href');
          if (targetId && targetId !== '#') {
            var targetEl = document.querySelector(targetId);
            if (targetEl) {
              targetEl.setAttribute('tabindex', '-1');
              targetEl.focus();
            }
          }
        });
      }
      console.log('CAS\'LEY v2 (Editorial Contemporánea) inicializada sin dependencias externas.');
    })();
