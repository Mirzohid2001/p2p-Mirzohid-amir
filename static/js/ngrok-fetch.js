/**
 * Обёртка fetch для обхода ngrok browser warning в iframe (Telegram Web).
 * Добавляет заголовок ngrok-skip-browser-warning к запросам на тот же origin.
 */
(function() {
  if (typeof window.fetch !== 'function') return;
  var isNgrok = /ngrok-free\.app|ngrok\.io/.test(window.location.hostname);
  if (!isNgrok) return;

  var originalFetch = window.fetch;
  window.fetch = function(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    var headers = options.headers;
    if (headers instanceof Headers) {
      headers.append('ngrok-skip-browser-warning', 'true');
    } else if (typeof headers === 'object' && !Array.isArray(headers)) {
      headers['ngrok-skip-browser-warning'] = 'true';
    }
    return originalFetch.call(this, url, options);
  };
})();
