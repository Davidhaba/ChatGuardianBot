// Перемикач тем
document.querySelector('.theme-toggle').addEventListener('click', () => {
    document.body.classList.toggle('light');
    const icon = document.querySelector('.theme-toggle i');
    icon.classList.toggle('fa-moon');
    icon.classList.toggle('fa-sun');
});

// Пошук
document.getElementById('search').addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase();
    document.querySelectorAll('.command').forEach(command => {
        const text = command.textContent.toLowerCase();
        command.style.display = text.includes(query) ? 'block' : 'none';
    });
});

// Копіювання команд
document.querySelectorAll('.copy-btn').forEach(button => {
    button.addEventListener('click', () => {
        navigator.clipboard.writeText(button.getAttribute('data-code'));
        button.innerHTML = '<i class="fas fa-check"></i>';
        setTimeout(() => button.innerHTML = '<i class="fas fa-copy"></i>', 2000);
    });
});

// Перевірка статусу
function checkStatus() {
    fetch('/')
        .then(response => {
            const statusText = document.getElementById('status-text');
            if (response.ok) {
                statusText.textContent = 'Онлайн';
                statusText.className = 'online';
            } else {
                statusText.textContent = 'Офлайн';
                statusText.className = 'offline';
            }
        })
        .catch(() => {
            const statusText = document.getElementById('status-text');
            statusText.textContent = 'Офлайн';
            statusText.className = 'offline';
        });
}
checkStatus();
setInterval(checkStatus, 15000);

// Плавний скрол
document.querySelectorAll('.sidebar nav a').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        e.preventDefault();
        document.querySelector(this.getAttribute('href')).scrollIntoView({
            behavior: 'smooth'
        });
    });
});