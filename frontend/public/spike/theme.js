// Theme and toggle for the temporary spike pages (plain script, no build). Same attribute and
// storage key as the app (src/lib/theme.ts). Deleted with the rest of /spike/ before the pilot.
(function () {
  var KEY = 'theme';

  function stored() {
    try {
      var value = window.localStorage.getItem(KEY);
      return value === 'light' || value === 'dark' ? value : null;
    } catch {
      return null;
    }
  }

  function system() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  }

  var theme = stored() || system();
  document.documentElement.dataset.theme = theme;

  window.addEventListener('DOMContentLoaded', function () {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'theme-toggle';

    function label() {
      button.textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
    }

    button.addEventListener('click', function () {
      theme = theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = theme;
      try {
        window.localStorage.setItem(KEY, theme);
      } catch {
        // Not remembered, but it still applies for this visit.
      }
      label();
    });

    label();
    document.body.appendChild(button);
  });
})();
