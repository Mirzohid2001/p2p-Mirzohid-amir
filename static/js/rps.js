// RPS Game JavaScript

let searchInterval = null;
let gameStatusInterval = null;
let moveTimerInterval = null;
let isMoveTimerRunning = false;
let currentGameId = null;
let searchTimer = 5;
let moveTimer = 8;
let gameFinalized = false;


function isGameReadyToFinalize(data) {
  // финал, когда есть result, или когда есть оба хода (для показа)
  return data.status === 'finished' && (data.result || (data.player1_move && data.player2_move));
}
document.addEventListener('click', function (e) {
  const btn = e.target.closest('#btn-rematch, #btn-rematch-cancelled');
  if (!btn) return;

  const gid = btn.dataset.gameId;
  console.log('REMATCH CLICK gid=', gid);

  startRematch(gid);
});

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
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
    if (typeof gameId !== 'undefined' && gameId) {
        currentGameId = gameId;
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
            window.location.href = '/rps/';
        });
    }
    
    const exitBtnCancelled = document.getElementById('btn-exit-cancelled');
    if (exitBtnCancelled) {
        exitBtnCancelled.addEventListener('click', function() {
            window.location.href = '/rps/';
        });
    }
});

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
    fetch('/rps/api/search/', {
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
        if (data.error) {
            showNotification(data.error, 'error');
            resetBetButtons();
            searchStatus.style.display = 'none';
            return;
        }
        
        if (data.opponent_found) {
            // Противник найден - переходим к игре
            showNotification('Противник найден!', 'success');
            setTimeout(() => {
                window.location.href = `/rps/game/${data.game_id}/`;
            }, 500);
        } else {
            // Начинаем поиск
            startSearchTimer(betAmount);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Ошибка при поиске игры', 'error');
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
    fetch('/rps/api/search/', {
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
        if (data.opponent_found) {
            clearInterval(searchInterval);
            window.location.href = `/rps/game/${data.game_id}/`;
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
    
    searchTimerEl.textContent = 'Подключение ...';
    
    fetch('/rps/api/bot/connect/', {
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
        if (data.error) {
            showNotification(data.error, 'error');
            resetBetButtons();
            searchStatus.style.display = 'none';
            return;
        }
        
        if (data.bot_connected) {
            showNotification('Подключен!', 'success');
            if (navigator.vibrate) {
                navigator.vibrate([100, 50, 100]);
            }
            setTimeout(() => {
                window.location.href = `/rps/game/${data.game_id}/`;
            }, 500);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Ошибка при подключении бота', 'error');
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
    fetch('/rps/api/search/cancel/', {
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
    
    showNotification('Поиск отменен', 'info');
}

// Отмена активной игры
function cancelGame() {
    console.log('cancelGame called, currentGameId:', currentGameId);
    
    if (!currentGameId) {
        console.error('currentGameId не установлен');
        showNotification('Ошибка: ID игры не найден', 'error');
        return;
    }
    
    if (!confirm('Вы уверены, что хотите отменить игру? Ставки будут возвращены.')) {
        return;
    }
    
    showLoading();
    
    console.log('Отправка запроса на отмену игры:', currentGameId);
    
    fetch('/rps/api/game/cancel/', {
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
            showNotification(data.message || 'Игра отменена, ставки возвращены', 'success');
            
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
                window.location.href = '/rps/';
            }, 1500);
        }
    })
    .catch(error => {
        hideLoading();
        console.error('Error canceling game:', error);
        showNotification('Ошибка при отмене игры: ' + error.message, 'error');
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

  gameStatusInterval = setInterval(() => {
    fetch(`/rps/api/game/${currentGameId}/status/`)
      .then(r => r.json())
      .then(data => {
        if (data.error) return;

        updateGameStatus(data);

        // ✅ cancelled — сразу стоп
        if (data.status === 'cancelled') {
          stopAllRpsIntervals();
          finalizeGameUI(data);
          return;
        }

        // ✅ finished — стопаем ТОЛЬКО если реально есть финальные данные
        if (isGameReadyToFinalize(data) && !gameFinalized) {
          gameFinalized = true;
          stopAllRpsIntervals();
          finalizeGameUI(data);
        }
      })
      .catch(console.error);
  }, 1200); // можно 1200-1500
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
                showNotification('Дополнительное время: +7 секунд', 'info');
            } else {
                // Время истекло
                clearInterval(moveTimerInterval);
                isMoveTimerRunning = false;
                showNotification('Время вышло!', 'error');
                timerEl.style.display = 'none';
            }
        }
    }, 1000);
}

function finalizeGameUI(data) {
  onGameFinishedUI();

  // результат (если есть элемент)
  const resultEl = document.getElementById('game-result');
  if (resultEl) {
    let text = 'Игра завершена';
    if (data.status === 'cancelled') text = 'Игра отменена';
    if (data.result === 'player1_win') text = 'Вы победили!';
    if (data.result === 'player2_win') text = 'Вы проиграли';
    if (data.result === 'draw') text = 'Ничья';
    resultEl.textContent = text;
    resultEl.style.display = 'block';
  }

  // показать кнопки (если они есть в HTML)
  const rematch = document.getElementById('btn-rematch');
  const exit = document.getElementById('btn-exit');
  if (rematch) rematch.style.display = 'inline-flex';
  if (exit) exit.style.display = 'inline-flex';

  // на всякий случай: скрыть кнопку отмены
  const cancelBtn = document.getElementById('btn-cancel-game');
  if (cancelBtn) cancelBtn.style.display = 'none';
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
    
    fetch('/rps/api/move/', {
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
        if (player1Move && typeof isPlayer1 !== 'undefined' && isPlayer1) {
            const moveEmoji = move === 'rock' ? '✊' : move === 'paper' ? '🖐️' : '✌️';
            player1Move.innerHTML = `<div class="move-icon move-${move}">${moveEmoji}</div>`;
            // Вибрация (если поддерживается)
            if (navigator.vibrate) {
                navigator.vibrate(100);
            }
        }
        
        if (data.game_finished) {
  if (!gameFinalized) {
    gameFinalized = true;

    // стопаем всё правильно
    stopAllRpsIntervals();

    // дорисуем противника, если пришёл ход
    if (data.player2_move) {
      const player2Move = document.getElementById('player2-move');
      if (player2Move) {
        const moveEmoji = data.player2_move === 'rock' ? '✊' :
                          data.player2_move === 'paper' ? '🖐️' : '✌️';
        player2Move.innerHTML = `<div class="move-icon move-${data.player2_move}">${moveEmoji}</div>`;
      }
    }

    // подсветка победителя (если result пришёл)
    const player1Card = document.querySelector('.player-card.player-1');
    const player2Card = document.querySelector('.player-card.player-2');

    if (data.result === 'player1_win') {
      player1Card?.classList.add('winner');
      player2Card?.classList.add('loser');
    } else if (data.result === 'player2_win') {
      player2Card?.classList.add('winner');
      player1Card?.classList.add('loser');
    }

    finalizeGameUI({ ...data, status: 'finished' });
  }
}

    })
    .catch(error => {
        hideLoading();
        console.error('Error:', error);
        showNotification('Ошибка при совершении хода', 'error');
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
    showNotification('Ошибка: ID игры не найден', 'error');
    return;
  }

  showLoading();

  fetch('/rps/api/rematch/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken'),
    },
    body: JSON.stringify({ game_id: gameId })
  })
  .then(r => r.json())
  .then(data => {
    hideLoading();

    if (data.error) {
      showNotification(data.error, 'error');
      return;
    }

    if (data.success && data.game_id) {
      showNotification('Новая игра создана!', 'success');

      // ✅ ВАЖНО: стопаем опросы старой игры
      stopAllRpsIntervals();

      // ✅ ВАЖНО: сразу уходим на новую игру
      window.location.replace(`/rps/game/${data.game_id}/`);
    }
  })
  .catch(err => {
    hideLoading();
    console.error(err);
    showNotification('Ошибка при создании новой игры', 'error');
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

