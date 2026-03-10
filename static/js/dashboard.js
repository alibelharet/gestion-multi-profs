/**
 * Dashboard logic for grade calculations and interactions
 */

// Initialize charts if data is present
document.addEventListener('DOMContentLoaded', function () {
    if (window.dashboardChartData && typeof Chart !== 'undefined') {
        const data = window.dashboardChartData;
        const ctxClasses = document.getElementById('chartClasses');
        const ctxDist = document.getElementById('chartDist');
        const ctxProgress = document.getElementById('chartProgress');

        const css = getComputedStyle(document.documentElement);
        const textColor = (css.getPropertyValue('--text') || '#f2f5f9').trim();
        const gridColor = (css.getPropertyValue('--border') || '#283446').trim();
        Chart.defaults.color = textColor;

        if (ctxClasses) {
            new Chart(ctxClasses, {
                type: 'bar',
                data: {
                    labels: data.classes.labels,
                    datasets: [{ label: 'Moyenne', data: data.classes.values, backgroundColor: '#0d6efd' }]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, max: 20, ticks: { color: textColor }, grid: { color: gridColor } },
                        x: { ticks: { color: textColor }, grid: { color: gridColor } }
                    }
                }
            });
        }

        if (ctxDist) {
            new Chart(ctxDist, {
                type: 'doughnut',
                data: { labels: data.distribution.labels, datasets: [{ data: data.distribution.values, backgroundColor: ['#198754', '#dc3545', '#6c757d'] }] },
                options: { responsive: true, plugins: { legend: { labels: { color: textColor } } } }
            });
        }

        if (ctxProgress) {
            new Chart(ctxProgress, {
                type: 'line',
                data: {
                    labels: data.progression.labels,
                    datasets: [
                        { label: 'T1', data: data.progression.t1, borderColor: '#0d6efd', backgroundColor: 'rgba(13,110,253,0.15)', tension: 0.25, fill: false },
                        { label: 'T2', data: data.progression.t2, borderColor: '#20c997', backgroundColor: 'rgba(32,201,151,0.15)', tension: 0.25, fill: false },
                        { label: 'T3', data: data.progression.t3, borderColor: '#fd7e14', backgroundColor: 'rgba(253,126,20,0.15)', tension: 0.25, fill: false }
                    ]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { labels: { color: textColor } } },
                    scales: {
                        y: { beginAtZero: true, max: 20, ticks: { color: textColor }, grid: { color: gridColor } },
                        x: { ticks: { color: textColor }, grid: { color: gridColor } }
                    }
                }
            });
        }
    }

    // Initial bindings for calculation
    var partInputs = document.querySelectorAll('input[id^="part_"]');
    partInputs.forEach(function (input) {
        var id = input.id.replace('part_', '');
        // We do not recalculate on load to avoid overwriting server data
        // but we could if needed: calculLive(id);
    });

    calculAddActivite();
    initDeleteMode();
});

function toNum(value) {
    var parsed = parseFloat(value);
    return isNaN(parsed) ? 0 : parsed;
}

function clampInput(input, maxValue) {
    if (!input) return 0;
    if (input.value === '') return 0;
    var value = toNum(input.value);
    if (value < 0) value = 0;
    if (value > maxValue) value = maxValue;
    input.value = value;
    return value;
}

function computeActivite(id) {
    var part = clampInput(document.getElementById('part_' + id), 3);
    var comport = clampInput(document.getElementById('comport_' + id), 6);
    var cah = clampInput(document.getElementById('cah_' + id), 5);
    var proj = clampInput(document.getElementById('proj_' + id), 4);
    var ao = clampInput(document.getElementById('ao_' + id), 2);

    var total = part + comport + cah + proj + ao;
    var totalRounded = total.toFixed(2);

    var actInput = document.getElementById('act_' + id);
    var actDisplay = document.getElementById('act_display_' + id);
    if (actInput) actInput.value = totalRounded;
    if (actDisplay) actDisplay.innerText = totalRounded;
    return total;
}

function calculLive(id) {
    var devInput = document.getElementById('dev_' + id);
    var compInput = document.getElementById('comp_' + id);
    var moySpan = document.getElementById('moy_' + id);

    var act = computeActivite(id);
    var dev = clampInput(devInput, 20);
    var comp = clampInput(compInput, 20);

    var moyenne = ((dev + act) / 2 + (comp * 2)) / 3;
    moySpan.innerText = moyenne.toFixed(2);

    if (moyenne < 10) {
        moySpan.className = 'text-danger fw-bold fs-5';
    } else {
        moySpan.className = 'text-success fw-bold fs-5';
    }
}

function calculAddActivite() {
    var fields = document.querySelectorAll('#addStudentModal .activite-part');
    var caps = [3, 6, 5, 4, 2];
    var total = 0;
    fields.forEach(function (input, index) {
        total += clampInput(input, caps[index] || 20);
    });

    var display = document.getElementById('activite_total_add');
    var hidden = document.getElementById('activite_hidden_add');
    if (display) display.value = 'Activite: ' + total.toFixed(2) + ' / 20';
    if (hidden) hidden.value = total.toFixed(2);
}

function initDeleteMode() {
    syncDeleteSelectionState();
    setDeleteMode(false);
}

function enterDeleteMode(event) {
    if (event) event.preventDefault();
    setDeleteMode(true);
    return false;
}

function setDeleteMode(active) {
    var container = document.getElementById('studentsTableContainer');
    if (!container) return false;

    container.classList.toggle('delete-mode', !!active);

    var toolbar = document.getElementById('deleteModeToolbar');
    if (toolbar) {
        toolbar.classList.toggle('d-none', !active);
    }

    if (!active) {
        var selectAll = document.querySelector('.select-all-delete');
        if (selectAll) {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        }

        var checkboxes = document.querySelectorAll('.check-delete');
        for (var i = 0, n = checkboxes.length; i < n; i++) {
            checkboxes[i].checked = false;
        }
    } else {
        var firstCheckbox = container.querySelector('.check-delete');
        if (firstCheckbox) firstCheckbox.focus();
    }

    syncDeleteSelectionState();
    return false;
}

function syncDeleteSelectionState() {
    var allCheckboxes = document.querySelectorAll('.check-delete');
    var checkedCount = document.querySelectorAll('.check-delete:checked').length;

    var counter = document.getElementById('deleteSelectionCount');
    if (counter) {
        if (checkedCount === 0) {
            counter.textContent = 'Aucun eleve selectionne';
        } else if (checkedCount === 1) {
            counter.textContent = '1 eleve selectionne';
        } else {
            counter.textContent = checkedCount + ' eleves selectionnes';
        }
    }

    var deleteButton = document.getElementById('deleteSelectedBtn');
    if (deleteButton) {
        deleteButton.disabled = checkedCount === 0;
    }

    var selectAll = document.querySelector('.select-all-delete');
    if (selectAll) {
        selectAll.checked = allCheckboxes.length > 0 && checkedCount === allCheckboxes.length;
        selectAll.indeterminate = checkedCount > 0 && checkedCount < allCheckboxes.length;
    }
}

function toggle(source) {
    var checkboxes = document.querySelectorAll('.check-delete');
    for (var i = 0, n = checkboxes.length; i < n; i++) {
        checkboxes[i].checked = source.checked;
    }
    syncDeleteSelectionState();
}

function submitDelete() {
    var checkboxes = document.querySelectorAll('.check-delete:checked');
    if (checkboxes.length === 0) {
        alert('Selectionnez au moins un eleve');
        return;
    }

    if (!confirm('Supprimer les eleves selectionnes ?')) return;

    var formDelete = document.getElementById('formMultiDelete');
    if (!formDelete) return;

    formDelete.querySelectorAll('input[name="ids"]').forEach(function (input) {
        input.remove();
    });

    checkboxes.forEach(function (chk) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'ids';
        input.value = chk.value;
        formDelete.appendChild(input);
    });
    formDelete.submit();
}
