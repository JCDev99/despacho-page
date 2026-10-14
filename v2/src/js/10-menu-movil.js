    // Control de navegación móvil editorial v2
    (function initV2Burger() {
      var burger = document.getElementById('v2BurgerBtn');
      var menu = document.getElementById('v2BurgerMenu');
      if (!burger || !menu) return;

      burger.addEventListener('click', function() {
        var isOpen = menu.classList.toggle('open');
        burger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      });

      document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && menu.classList.contains('open')) {
          menu.classList.remove('open');
          burger.setAttribute('aria-expanded', 'false');
          burger.focus();
        }
      });

      var links = menu.querySelectorAll('a');
      for (var i = 0; i < links.length; i++) {
        links[i].addEventListener('click', function() {
          menu.classList.remove('open');
          burger.setAttribute('aria-expanded', 'false');
        });
      }
    })();
