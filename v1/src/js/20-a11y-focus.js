    // Control de accesibilidad y foco por teclado v1
    (function initA11y() {
      // Garantizar que todos los enlaces con anclas muevan el foco al objetivo
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
      console.log('CAS\'LEY v1 (Institucional Sobria) inicializada sin dependencias externas.');
    })();
