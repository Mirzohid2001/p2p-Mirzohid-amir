// RPS Game JavaScript
function tgUrl(url) {
  var id = (typeof window !== 'undefined' && window.__TG_ID);
  return (id && url) ? url + (url.indexOf('?') >= 0 ? '&' : '?') + 'tg_id=' + id : url;
}
function navigateTo(url) {
  window.location.href = tgUrl(url);
}
const t = (window.I18N_RPS || {});
const tr = (key, fallback) => (t[key] != null ? t[key] : fallback);
let searchInterval = null;
let gameStatusInterval = null;
let moveTimerInterval = null;
let isMoveTimerRunning = false;
let currentGameId = null;
// isPlayer1 из шаблона — const и не меняется; при подгрузке новой партии без перезагрузки берём значение отсюда
let currentIsPlayer1 = (typeof isPlayer1 !== 'undefined') ? !!isPlayer1 : true;
let rematchInFlight = false;
// пауза между партиями (сервер не даёт начать новую раньше, чем через 5 с)
const GAME_COOLDOWN_SECONDS = 5;
let rematchCooldownInterval = null;

// Проверка «вы не бот?»: сервер не даёт начать партию, пока игрок не нажмёт нужный фрукт.
// onPassed — что сделать после успешной проверки (повторить «Ещё раз», поиск и т.п.)
function showHumanCheck(check, onPassed, message) {
  hideLoading();
  const old = document.getElementById('human-check');
  if (old) old.remove();

  const ov = document.createElement('div');
  ov.id = 'human-check';
  ov.style.cssText = 'position:fixed;inset:0;z-index:10001;background:rgba(10,14,40,.78);display:flex;align-items:center;justify-content:center;padding:16px';
  ov.innerHTML = `
    <div style="background:linear-gradient(160deg,#3D50C7,#6B75E6);color:#fff;border-radius:18px;padding:20px 18px;max-width:340px;width:100%;text-align:center;box-shadow:0 12px 40px rgba(0,0,0,.45)">
      <div style="font-size:18px;font-weight:700;margin-bottom:6px">${tr('hc_title', '🤖 Проверка: вы не бот?')}</div>
      <div style="opacity:.92;margin-bottom:14px">${tr('hc_prompt', 'Нажмите на')} <span class="hc-target" style="font-size:28px;vertical-align:middle"></span></div>
      <div class="hc-grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px"></div>
      <div class="hc-msg" style="min-height:20px;margin-top:12px;color:#ffd6e2;font-size:14px"></div>
    </div>`;
  ov.querySelector('.hc-target').textContent = check.target;
  ov.querySelector('.hc-msg').textContent = message || '';

  let busy = false;
  const answer = (choice) => {
    if (busy) return;
    busy = true;
    fetch(tgUrl('/rps/api/human-check/'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: check.id, choice: choice })
    })
      .then(r => r.json())
      .then(d => {
        busy = false;
        if (d.passed) {
          ov.remove();
          showNotification(tr('hc_ok', 'Спасибо! Можно играть'), 'success');
          if (onPassed) onPassed();
        } else if (d.human_check) {
          showHumanCheck(d.human_check, onPassed, d.error || '');
        }
      })
      .catch(() => { busy = false; });
  };

  const grid = ov.querySelector('.hc-grid');
  (check.options || []).forEach(f => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = f;
    b.style.cssText = 'font-size:34px;line-height:1;padding:14px 0;border-radius:14px;border:0;background:rgba(255,255,255,.16);cursor:pointer';
    b.addEventListener('click', () => answer(f));
    grid.appendChild(b);
  });
  document.body.appendChild(ov);
}

function startRematchCooldown(seconds) {
  if (rematchCooldownInterval) { clearInterval(rematchCooldownInterval); rematchCooldownInterval = null; }
  const buttons = [...document.querySelectorAll('#btn-rematch, #btn-rematch-cancelled')];
  if (!buttons.length) return;
  buttons.forEach(b => {
    if (!b.dataset.label) b.dataset.label = b.textContent.trim();
    b.disabled = true;
    b.style.opacity = '0.6';
  });
  let left = Math.max(1, Math.ceil(seconds));
  const paint = () => buttons.forEach(b => { b.textContent = `${b.dataset.label} (${left})`; });
  paint();
  rematchCooldownInterval = setInterval(() => {
    left--;
    if (left <= 0) {
      clearInterval(rematchCooldownInterval);
      rematchCooldownInterval = null;
      buttons.forEach(b => { b.textContent = b.dataset.label; b.disabled = false; b.style.opacity = ''; });
      return;
    }
    paint();
  }, 1000);
}
let searchTimer = 5;
let moveTimer = 8;
let gameFinalized = false;
let awaitingFinalize = false;
let finalizeAttempts = 0;
let finalizeInterval = null;

function isFinalizeReady(data) {
  // считаем финал готовым, если пришёл result ИЛИ пришёл ход соперника
  // (в бот-игре result может приходить позже, но player2_move обычно уже есть)
  return !!data.result || (data.player1_move && data.player2_move);
}

function stopFinalizeLoop() {
  if (finalizeInterval) {
    clearInterval(finalizeInterval);
    finalizeInterval = null;
  }
  finalizeAttempts = 0;
}

function forceFinalizeLoop() {
  if (finalizeInterval) return; // уже запущен
  awaitingFinalize = true;
  finalizeAttempts = 0;

  const finalizeTick = () => {
    finalizeAttempts++;

    fetch(tgUrl(`/rps/api/game/${currentGameId}/status/`))
      .then(r => r.json())
      .then(data => {
        if (data?.error) return;
        if (gameFinalized) return; // результат уже показан предыдущим ответом

        // обновим UI хоть чем-то (например, ходами)
        updateGameStatus(data);

        if (isFinalizeReady(data)) {
          gameFinalized = true;
          awaitingFinalize = false;

          stopFinalizeLoop();
          stopAllRpsIntervals();     // стопаем общий polling
          finalizeGameUI({ ...data, status: 'finished' });
        }

        // таймаут: 10-12 секунд
        if (finalizeAttempts >= 12) {
          stopFinalizeLoop();
          showNotification(tr('result_too_long', 'Результат долго не приходит. Обнови страницу.'), 'error');

        }
      })
      .catch(() => {});
  };

  finalizeInterval = setInterval(finalizeTick, 900);
  finalizeTick(); // сразу: сервер обычно уже знает результат в момент ответа на ход
}


function isGameReadyToFinalize(data) {
  // финал, когда есть result, или когда есть оба хода (для показа)
  return data.status === 'finished' && (data.result || (data.player1_move && data.player2_move));
}
document.addEventListener('click', function (e) {
  const btn = e.target.closest('#btn-rematch, #btn-rematch-cancelled');
  if (!btn) return;

  // у кнопки из серверного шаблона нет data-game-id — берём текущую игру
  const gid = btn.dataset.gameId || currentGameId;
  startRematch(gid);
});

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
    currentGameId = (typeof gameId !== 'undefined' && gameId) ? gameId : null;
    initRpsPage();
});

// Навешивает обработчики на текущее содержимое .rps-game-container.
// Вызывается при загрузке страницы и после подгрузки новой партии без перезагрузки.
function initRpsPage() {
    // Если мы на странице выбора ставки
    const betButtons = document.querySelectorAll('.bet-btn');
    if (betButtons.length > 0) {
        betButtons.forEach(btn => {
            btn.addEventListener('click', function() {
                const betAmount = this.dataset.bet;
                startGameSearch(betAmount);
            });
        });
    }

    
    // Кнопка отмены поиска
    const cancelSearchBtn = document.getElementById('btn-cancel-search');
    if (cancelSearchBtn) {
        cancelSearchBtn.addEventListener('click', function() {
            cancelGameSearch();
        });
    }

    // Если мы на странице игры
    if (currentGameId) {
        startGameStatusPolling();
        
        // Обработчики ходов
        const moveButtons = document.querySelectorAll('.move-btn');
        moveButtons.forEach(btn => {
            btn.addEventListener('click', function() {
                const move = this.dataset.move;
                makeMove(move);
            });
        });
        
        // Кнопка отмены игры
        const cancelGameBtn = document.getElementById('btn-cancel-game');
        if (cancelGameBtn) {
            cancelGameBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                console.log('Cancel game button clicked, gameId:', currentGameId);
                cancelGame();
            });
        } else {
            console.warn('Кнопка отмены игры не найдена');
        }
    }
    
    // Кнопка "Выйти"
    const exitBtn = document.getElementById('btn-exit');
    if (exitBtn) {
        exitBtn.addEventListener('click', function() {
            navigateTo('/rps/');
        });
    }
    
    const exitBtnCancelled = document.getElementById('btn-exit-cancelled');
    if (exitBtnCancelled) {
        exitBtnCancelled.addEventListener('click', function() {
            navigateTo('/rps/');
        });
    }
}

// Сбрасывает состояние прошлой партии перед показом новой
function resetGameState() {
    stopFinalizeLoop();
    stopAllRpsIntervals();
    if (rematchCooldownInterval) { clearInterval(rematchCooldownInterval); rematchCooldownInterval = null; }
    gameFinalized = false;
    awaitingFinalize = false;
    additionalTimeUsed = false;
    moveTimer = 8;
    searchTimer = 5;
}

// Показывает партию без перезагрузки страницы: берём готовый HTML партии с сервера
// и подменяем только игровой блок. Если что-то пошло не так — обычный переход.
function loadGameInPlace(newGameId) {
    const url = `/rps/game/${newGameId}/`;
    const container = document.querySelector('.rps-game-container');
    if (!container || !window.fetch || !window.DOMParser) {
        window.location.replace(tgUrl(url));
        return Promise.resolve();
    }

    resetGameState();

    return fetch(tgUrl(url), { credentials: 'same-origin' })
        .then(r => {
            // сессия слетела — сервер отправил на страницу входа: пусть разбирается обычный переход
            if (!r.ok || (r.redirected && r.url.indexOf('/rps/game/') === -1)) {
                throw new Error('soft navigation failed: ' + r.status);
            }
            return r.text();
        })
        .then(html => {
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const fresh = doc.querySelector('.rps-game-container');
            const idMatch = html.match(/const gameId = (\d+|null);/);
            const p1Match = html.match(/const isPlayer1 = (true|false);/);
            if (!fresh || !idMatch) throw new Error('unexpected game page');

            container.innerHTML = fresh.innerHTML;
            currentGameId = idMatch[1] === 'null' ? null : Number(idMatch[1]);
            currentIsPlayer1 = p1Match ? p1Match[1] === 'true' : true;
            try { history.replaceState(history.state, '', url); } catch (e) {}
            window.scrollTo(0, 0);
            initRpsPage();
        })
        .catch(err => {
            console.warn('loadGameInPlace fallback:', err);
            window.location.replace(tgUrl(url));
        });
}

// Поиск игры
function startGameSearch(betAmount) {
    const betButtons = document.querySelectorAll('.bet-btn');
    const betOptions = document.querySelector('.bet-options');
    
    // Скрываем кнопки ставок
    if (betOptions) {
        betOptions.style.display = 'none';
    }
    
    const searchStatus = document.getElementById('search-status');
    const searchTimerEl = document.getElementById('search-timer');
    const cancelSearchBtn = document.getElementById('btn-cancel-search');
    
    // Показываем индикатор поиска
    searchStatus.style.display = 'block';
    if (cancelSearchBtn) {
        cancelSearchBtn.style.display = 'block';
    }
    searchTimer = 5;
    searchTimerEl.textContent = searchTimer;
    
    // Вибрация при начале поиска
    if (navigator.vibrate) {
        navigator.vibrate(100);
    }
    
    // Отправляем запрос на поиск
    fetch(tgUrl('/rps/api/search/'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({
            bet_amount: betAmount
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.human_check) {
            resetBetButtons();
            searchStatus.style.display = 'none';
            showHumanCheck(data.human_check, () => startGameSearch(betAmount));
            return;
        }
        if (data.error) {
            showNotification(data.error, 'error');
            resetBetButtons();
            searchStatus.style.display = 'none';
            return;
        }

        if (data.opponent_found) {
            // Противник найден - переходим к игре
            showNotification(tr('opponent_found', 'Противник найден!'), 'success');

            setTimeout(() => {
                loadGameInPlace(data.game_id);
            }, 500);
        } else {
            // Начинаем поиск
            startSearchTimer(betAmount);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification(tr('search_error', 'Ошибка при поиске игры'), 'error');
        resetBetButtons();
        searchStatus.style.display = 'none';
    });
}

// Таймер поиска
function startSearchTimer(betAmount) {
    const searchTimerEl = document.getElementById('search-timer');
    
    searchInterval = setInterval(() => {
        searchTimer--;
        searchTimerEl.textContent = searchTimer;
        
        if (searchTimer <= 0) {
            clearInterval(searchInterval);
            // Подключаем бота
            connectBot(betAmount);
        } else {
            // Продолжаем поиск
            checkForOpponent(betAmount);
        }
    }, 1000);
}

// Проверка противника
function checkForOpponent(betAmount) {
    fetch(tgUrl('/rps/api/search/'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({
            bet_amount: betAmount
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.human_check) {
            clearInterval(searchInterval);
            searchInterval = null;
            resetBetButtons();
            const st = document.getElementById('search-status');
            if (st) st.style.display = 'none';
            showHumanCheck(data.human_check, () => startGameSearch(betAmount));
            return;
        }
        if (data.opponent_found) {
            clearInterval(searchInterval);
            searchInterval = null;
            loadGameInPlace(data.game_id);
        }
    })
    .catch(error => {
        console.error('Error:', error);
    });
}

// Подключение бота
function connectBot(betAmount) {
    const searchStatus = document.getElementById('search-status');
    const searchTimerEl = document.getElementById('search-timer');
    
    searchTimerEl.textContent = tr('bot_connecting', 'Подключение ...');

    
    fetch(tgUrl('/rps/api/bot/connect/'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({
            bet_amount: betAmount
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.human_check) {
            resetBetButtons();
            searchStatus.style.display = 'none';
            showHumanCheck(data.human_check, () => startGameSearch(betAmount));
            return;
        }
        if (data.error) {
            showNotification(data.error, 'error');
            resetBetButtons();
            searchStatus.style.display = 'none';
            return;
        }

        if (data.bot_connected) {
            showNotification(tr('bot_connected', 'Подключен!'), 'success');

            if (navigator.vibrate) {
                navigator.vibrate([100, 50, 100]);
            }
            setTimeout(() => {
                loadGameInPlace(data.game_id);
            }, 500);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification(tr('bot_connect_error', 'Ошибка при подключении бота'), 'error');
        resetBetButtons();
        searchStatus.style.display = 'none';
    });
}

// Отмена поиска игры
function cancelGameSearch() {
    // Останавливаем таймер поиска
    if (searchInterval) {
        clearInterval(searchInterval);
        searchInterval = null;
    }
    
    // Удаляем из очереди на сервере
    fetch(tgUrl('/rps/api/search/cancel/'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        }
    }).catch(error => {
        console.error('Error canceling search:', error);
    });
    
    // Скрываем статус поиска
    const searchStatus = document.getElementById('search-status');
    const cancelSearchBtn = document.getElementById('btn-cancel-search');
    if (searchStatus) {
        searchStatus.style.display = 'none';
    }
    if (cancelSearchBtn) {
        cancelSearchBtn.style.display = 'none';
    }
    
    // Восстанавливаем кнопки ставок
    resetBetButtons();
    
    showNotification(tr('search_cancelled', 'Поиск отменен'), 'info');

}

// Отмена активной игры
function cancelGame() {
    console.log('cancelGame called, currentGameId:', currentGameId);
    
    if (!currentGameId) {
        console.error('currentGameId не установлен');
        showNotification(tr('id_not_found', 'Ошибка: ID игры не найден'), 'error');

        return;
    }
    
    if (!confirm(tr('cancel_confirm', 'Вы уверены, что хотите отменить игру? Ставки будут возвращены.'))) {
  return;
}

    
    showLoading();
    
    console.log('Отправка запроса на отмену игры:', currentGameId);
    
    fetch(tgUrl('/rps/api/game/cancel/'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({
            game_id: currentGameId
        })
    })
    .then(response => {
        console.log('Response status:', response.status);
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || `HTTP error! status: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('Response data:', data);
        hideLoading();
        
        if (data.error) {
            showNotification(data.error, 'error');
            return;
        }
        
        if (data.success) {
            showNotification(data.message || tr('cancel_success', 'Игра отменена, ставки возвращены'), 'success');

            
            // Останавливаем опросы
            if (gameStatusInterval) {
                clearInterval(gameStatusInterval);
                gameStatusInterval = null;
            }
            if (moveTimerInterval) {
                clearInterval(moveTimerInterval);
                moveTimerInterval = null;
            }
            if (searchInterval) {
                clearInterval(searchInterval);
                searchInterval = null;
            }
            
            // Переходим на главную страницу
            setTimeout(() => {
                navigateTo('/rps/');
            }, 1500);
        }
    })
    .catch(error => {
        hideLoading();
        console.error('Error canceling game:', error);
        showNotification(tr('cancel_error_prefix', 'Ошибка при отмене игры: ') + error.message, 'error');

    });
}

// Сброс кнопок ставок
function resetBetButtons() {
    const betButtons = document.querySelectorAll('.bet-btn');
    const betOptions = document.querySelector('.bet-options');
    
    // Показываем кнопки ставок обратно
    if (betOptions) {
        betOptions.style.display = 'grid';
    }
    
    betButtons.forEach(btn => {
        btn.disabled = false;
        btn.style.opacity = '1';
    });
}

// Опрос статуса игры
function startGameStatusPolling() {
  if (!currentGameId) return;

  // ✅ чтобы не плодить интервалы
  if (gameStatusInterval) clearInterval(gameStatusInterval);

  gameStatusInterval = setInterval(() => {
    fetch(tgUrl(`/rps/api/game/${currentGameId}/status/`))
      .then(r => r.json())
      .then(data => {
        if (data?.error) return;

        updateGameStatus(data);

        if (data.status === 'cancelled' && !gameFinalized) {
          gameFinalized = true;
          stopFinalizeLoop();
          stopAllRpsIntervals();
          finalizeGameUI(data);
          return;
        }

        // ✅ если уже “дожимаем” — НЕ трогаем finalize тут
        if (awaitingFinalize) return;

        // ✅ финализируем по обычной логике (если хочешь оставить)
        if (isGameReadyToFinalize(data) && !gameFinalized) {
          gameFinalized = true;
          stopAllRpsIntervals();
          finalizeGameUI(data);
        }
      })
      .catch(() => {});
  }, 1200);
}



// Обновление статуса игры
function updateGameStatus(data) {
        // Обновляем ходы
        if (data.player1_move) {
            const player1Move = document.getElementById('player1-move');
            if (player1Move) {
                const moveEmoji1 = data.player1_move === 'rock' ? '✊' : 
                                  data.player1_move === 'paper' ? '🖐️' : '✌️';
                player1Move.innerHTML = `<div class="move-icon move-${data.player1_move}">${moveEmoji1}</div>`;
            }
        }
        
        if (data.player2_move) {
            const player2Move = document.getElementById('player2-move');
            if (player2Move) {
                const moveEmoji2 = data.player2_move === 'rock' ? '✊' : 
                                  data.player2_move === 'paper' ? '🖐️' : '✌️';
                player2Move.innerHTML = `<div class="move-icon move-${data.player2_move}">${moveEmoji2}</div>`;
            }
        }
    
    // Обновляем имя бота, если это игра с ботом
    if (data.is_bot_game && data.bot_name) {
        const player2Card = document.querySelector('.player-card.player-2 .player-name');
        if (player2Card) {
            player2Card.textContent = data.bot_name;
        }
    }
    
    // Обновляем банк
    if (data.game_bank) {
        const gameBank = document.getElementById('game-bank');
        if (gameBank) {
            gameBank.textContent = `${data.game_bank.toFixed(0)} FL`;
        }
    }
    
    // Показываем/скрываем кнопку отмены в зависимости от статуса
    const cancelBtn = document.getElementById('btn-cancel-game');
    if (cancelBtn) {
        if (data.status === 'playing' || data.status === 'betting') {
            cancelBtn.style.display = 'block';
        } else {
            cancelBtn.style.display = 'none';
        }
    }
    
    // Запускаем таймер хода
    if (data.status === 'playing' || data.status === 'betting') {
        startMoveTimer();
    }
}

// Таймер хода (8 секунд + дополнительно 7 секунд)
let additionalTimeUsed = false;

function startMoveTimer() {
    const timerEl = document.getElementById('game-timer');
    const timerValue = document.getElementById('timer-value');
    
    if (!timerEl || !timerValue) return;
    if (isMoveTimerRunning) return; // не стартуем новый, если уже крутится
    
    timerEl.style.display = 'block';
    moveTimer = 8;  // Основной таймер: 8 секунд
    additionalTimeUsed = false;
    timerValue.textContent = moveTimer;
    timerEl.classList.remove('warning', 'danger');
    
    if (moveTimerInterval) {
        clearInterval(moveTimerInterval);
    }
    isMoveTimerRunning = true;
    
    moveTimerInterval = setInterval(() => {
        moveTimer--;
        timerValue.textContent = moveTimer;
        
        // Изменяем цвет в зависимости от оставшегося времени
        if (moveTimer <= 1) {
            timerEl.classList.add('danger');
            timerEl.classList.remove('warning');
            if (navigator.vibrate) navigator.vibrate(50);
        } else if (moveTimer <= 2) {
            timerEl.classList.add('warning');
            timerEl.classList.remove('danger');
        }
        
        if (moveTimer <= 0) {
            if (!additionalTimeUsed) {
                // Добавляем дополнительно 7 секунд (чуть больше толерантности)
                additionalTimeUsed = true;
                moveTimer = 7;
                timerValue.textContent = moveTimer;
                timerEl.classList.remove('warning', 'danger');
                showNotification(tr('time_extra', 'Дополнительное время: +7 секунд'), 'info');

            } else {
                // Время истекло
                clearInterval(moveTimerInterval);
                isMoveTimerRunning = false;
                showNotification(tr('time_over', 'Время вышло!'), 'error');
                timerEl.style.display = 'none';
            }
        }
    }, 1000);
}
document.addEventListener('click', function(e) {
  const exit = e.target.closest('#btn-exit');
  if (!exit) return;
  navigateTo('/rps/');
});
function finalizeGameUI(data) {
  onGameFinishedUI(); // выключаем кнопки, таймеры
    hideMovePanel();

  const normalized = normalizeResult(data);

  // определяем выиграл ли текущий юзер
  let userWin = false;
  let userLose = false;
  let isDraw = false;

  if (normalized === 'draw') {
    isDraw = true;
  } else if (normalized === 'player1_win') {
    userWin = currentIsPlayer1;
    userLose = !currentIsPlayer1;
  } else if (normalized === 'player2_win') {
    userWin = !currentIsPlayer1;
    userLose = currentIsPlayer1;
  }

  const bank = (data.game_bank != null) ? Number(data.game_bank).toFixed(0) : null;

  const resultEl = document.getElementById('game-result');
  if (!resultEl) return;

  // если cancelled
  if (data.status === 'cancelled') {
    resultEl.innerHTML = `
      <div class="result-message result-draw">
        <h2>${tr('game_cancelled_title', '⏱️ Игра отменена')}</h2>
        <p>${tr('game_cancelled_text', 'Один из игроков не сделал выбор. Ставки возвращены.')}</p>
      </div>
      <div class="result-actions">
            <button class="btn-rematch" id="btn-rematch" data-game-id="${currentGameId}">${tr('rematch_btn','🔁 Ещё раз')}</button>

            <button class="btn-exit" id="btn-exit">${tr('exit_btn','🚪 Выйти')}</button>

      </div>
    `;
  } else {
    // finished
    if (isDraw) {
  resultEl.innerHTML = `
    <div class="result-message result-draw">
      <h2>${tr('draw_title', '🤝 Ничья!')}</h2>
      <p>${tr('draw_text', 'Ставки возвращены')}</p>
    </div>
    <div class="result-actions">
      <button class="btn-rematch" id="btn-rematch" data-game-id="${currentGameId}">${tr('rematch_btn','🔁 Ещё раз')}</button>
      <button class="btn-exit" id="btn-exit">${tr('exit_btn','🚪 Выйти')}</button>
    </div>
  `;
} else if (userWin) {
  resultEl.innerHTML = `
    <div class="result-message result-win">
      <h2>${tr('win_title', '🎉 Вы выиграли!')}</h2>
      ${bank ? `<p>${tr('win_got_prefix','Вы получили')} ${bank} FL</p>` : `<p>${tr('congrats','Поздравляем!')}</p>`}
    </div>
    <div class="result-actions">
      <button class="btn-rematch" id="btn-rematch" data-game-id="${currentGameId}">${tr('rematch_btn','🔁 Ещё раз')}</button>
      <button class="btn-exit" id="btn-exit">${tr('exit_btn','🚪 Выйти')}</button>
    </div>
  `;
} else if (userLose) {
  resultEl.innerHTML = `
    <div class="result-message result-loss">
      <h2>${tr('lose_title', '😔 Вы проиграли')}</h2>
      <p>${tr('lose_text', 'Попробуйте ещё раз!')}</p>
    </div>
    <div class="result-actions">
      <button class="btn-rematch" id="btn-rematch" data-game-id="${currentGameId}">${tr('rematch_btn','🔁 Ещё раз')}</button>
      <button class="btn-exit" id="btn-exit">${tr('exit_btn','🚪 Выйти')}</button>
    </div>
  `;
} else {
  resultEl.innerHTML = `
    <div class="result-message result-draw">
      <h2>${tr('game_finished_title', '✅ Игра завершена')}</h2>
      <p>${tr('game_finished_text', 'Результат получен.')}</p>
    </div>
    <div class="result-actions">
      <button class="btn-rematch" id="btn-rematch" data-game-id="${currentGameId}">${tr('rematch_btn','🔁 Ещё раз')}</button>
      <button class="btn-exit" id="btn-exit">${tr('exit_btn','🚪 Выйти')}</button>
    </div>
  `;
}

  }

  resultEl.style.display = 'block';

  // прячем отмену игры (на всякий)
  const cancelBtn = document.getElementById('btn-cancel-game');
  if (cancelBtn) cancelBtn.style.display = 'none';

  // 5 секунд до следующей партии
  startRematchCooldown(GAME_COOLDOWN_SECONDS);
}

function hideMovePanel() {
  const panel = document.querySelector('.move-panel');
  if (panel) {
    panel.style.display = 'none';
  }
}

function onGameFinishedUI() {
  document.querySelectorAll('.move-btn').forEach(b => b.disabled = true);

  const timerEl = document.getElementById('game-timer');
  if (timerEl) timerEl.style.display = 'none';
}
// Совершение хода
function makeMove(move) {
    if (!currentGameId) return;
    
    const moveButtons = document.querySelectorAll('.move-btn');
    moveButtons.forEach(btn => {
        btn.disabled = true;
        btn.classList.remove('selected');
    });
    
    // Выделяем выбранный ход
    const selectedBtn = document.querySelector(`.move-btn[data-move="${move}"]`);
    if (selectedBtn) {
        selectedBtn.classList.add('selected');
    }
    
    // Показываем индикатор загрузки
    showLoading();
    
    fetch(tgUrl('/rps/api/move/'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({
            game_id: currentGameId,
            move: move
        })
    })
    .then(response => response.json())
    .then(data => {
        hideLoading();
        
        if (data.error) {
            showNotification(data.error, 'error');
            moveButtons.forEach(btn => btn.disabled = false);
            return;
        }
        
        // Обновляем отображение хода с анимацией
        const player1Move = document.getElementById('player1-move');
        if (player1Move && currentIsPlayer1) {
            const moveEmoji = move === 'rock' ? '✊' : move === 'paper' ? '🖐️' : '✌️';
            player1Move.innerHTML = `<div class="move-icon move-${move}">${moveEmoji}</div>`;
            // Вибрация (если поддерживается)
            if (navigator.vibrate) {
                navigator.vibrate(100);
            }
        }
        
        if (data.game_finished) {
  onGameFinishedUI();
  showNotification(tr('wait_result', 'Ожидаем результат...'), 'info');


  // ❗ запускаем принудительный “дожим” результата
  forceFinalizeLoop();
}



    })
    .catch(error => {
        hideLoading();
        console.error('Error:', error);
        showNotification(tr('move_error', 'Ошибка при совершении хода'), 'error');
        moveButtons.forEach(btn => btn.disabled = false);
    });
}

// Получение CSRF токена
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Показ уведомлений
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 25px;
        background: ${type === 'error' ? '#FF5A8F' : type === 'success' ? '#5AFF75' : '#3D50C7'};
        color: white;
        border-radius: 10px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
        z-index: 10000;
        animation: slideIn 0.3s ease-out;
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}
function normalizeResult(data) {
  // 1) если сервер уже прислал result в твоём формате
  const r = data?.result;

  // 2) частые варианты
  if (r === 'player1_win' || r === 'p1' || r === 'player1' || r === 'win' || r === 'won') return 'player1_win';
  if (r === 'player2_win' || r === 'p2' || r === 'player2' || r === 'lose' || r === 'lost') return 'player2_win';
  if (r === 'draw' || r === 'tie') return 'draw';

  // 3) если сервер шлёт winner: 1/2/0
  if (data?.winner === 1) return 'player1_win';
  if (data?.winner === 2) return 'player2_win';
  if (data?.winner === 0) return 'draw';

  // 4) если сервер шлёт outcome: 'WIN'/'LOSE'/'DRAW'
  const o = (data?.outcome || '').toLowerCase();
  if (o === 'win') return 'player1_win';
  if (o === 'lose') return 'player2_win';
  if (o === 'draw') return 'draw';

  return null;
}

// Показ загрузки
function showLoading() {
    const overlay = document.createElement('div');
    overlay.className = 'loading-overlay';
    overlay.id = 'loading-overlay';
    overlay.innerHTML = '<div class="loading-spinner"></div>';
    document.body.appendChild(overlay);
}

// Скрытие загрузки
function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.remove();
    }
}

// Начать новую игру с тем же соперником
function stopAllRpsIntervals() {
  if (searchInterval) { clearInterval(searchInterval); searchInterval = null; }
  if (gameStatusInterval) { clearInterval(gameStatusInterval); gameStatusInterval = null; }
  if (moveTimerInterval) { clearInterval(moveTimerInterval); moveTimerInterval = null; }
  isMoveTimerRunning = false;
}

function startRematch(gameId) {
  if (!gameId) {
    showNotification(tr('id_not_found', 'Ошибка: ID игры не найден'), 'error');

    return;
  }
  // двойное нажатие не должно создавать две игры
  if (rematchInFlight) return;
  rematchInFlight = true;

  showLoading();

  fetch(tgUrl('/rps/api/rematch/'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken'),
    },
    body: JSON.stringify({ game_id: gameId })
  })
  .then(r => r.json())
  .then(data => {
    if (data.human_check) {
      hideLoading();
      rematchInFlight = false;
      showHumanCheck(data.human_check, () => startRematch(gameId));
      return;
    }
    if (data.cooldown) {
      // сервер просит подождать — показываем отсчёт на кнопке
      hideLoading();
      rematchInFlight = false;
      startRematchCooldown(data.cooldown);
      return;
    }
    if (data.error) {
      hideLoading();
      rematchInFlight = false;
      showNotification(data.error, 'error');
      return;
    }

    if (data.success && data.game_id) {
      // новая партия на месте, без перезагрузки страницы
      return loadGameInPlace(data.game_id).then(() => {
        hideLoading();
        rematchInFlight = false;
      });
    }
    hideLoading();
    rematchInFlight = false;
  })
  .catch(err => {
    hideLoading();
    rematchInFlight = false;
    console.error(err);
    showNotification(tr('rematch_error', 'Ошибка при создании новой игры'), 'error');

  });
}


// Добавляем CSS для уведомлений
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

