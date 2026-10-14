    // Control accesible del menú móvil v1
    (function initMobileMenu() {
      var btn = document.getElementById('v1MobileMenuBtn');
      var menu = document.getElementById('v1MobileMenu');
      if (!btn || !menu) return;

      btn.addEventListener('click', function() {
        var isOpen = menu.classList.toggle('open');
        btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      });

      // Cerrar al pulsar Escape
      document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && menu.classList.contains('open')) {
          menu.classList.remove('open');
          btn.setAttribute('aria-expanded', 'false');
          btn.focus();
        }
      });

      // Cerrar al pulsar un enlace de navegación
      var links = menu.querySelectorAll('a');
      for (var i = 0; i < links.length; i++) {
        links[i].addEventListener('click', function() {
          menu.classList.remove('open');
          btn.setAttribute('aria-expanded', 'false');
        });
      }
    })();
