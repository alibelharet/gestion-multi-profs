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

    calculAddActivite();
    initDeleteMode();
    initSaveGuard();
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
    if (actInput) actInput.value = totalRounded;
    return total;
}

function updateMoyenne(id, activite) {
    var devInput = document.getElementById('dev_' + id);
    var compInput = document.getElementById('comp_' + id);
    var moySpan = document.getElementById('moy_' + id);

    var dev = clampInput(devInput, 20);
    var comp = clampInput(compInput, 20);

    var moyenne = ((dev + activite) / 2 + (comp * 2)) / 3;
    if (!moySpan) return;
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

function initSaveGuard() {
    var form = document.getElementById('formSaveAll');
    if (!form || form.dataset.canEdit !== 'true') return;

    var inputs = Array.prototype.slice.call(form.querySelectorAll(
        'input[name="activite"], input[name="devoir"], input[name="compo"], input[name="participation"], input[name="comportement"], input[name="cahier"], input[name="projet"], input[name="assiduite_outils"]'
    )).filter(function (input) {
        return !input.readOnly && !input.disabled;
    });
    if (!inputs.length) return;

    var initialValues = new Map();
    var isSubmitting = false;
    var status = document.getElementById('saveStatus');
    var bar = document.getElementById('unsavedChangesBar');
    var barText = document.getElementById('unsavedChangesText');

    inputs.forEach(function (input) {
        initialValues.set(input, input.value);
        input.addEventListener('input', syncSaveState);
        input.addEventListener('change', syncSaveState);
    });

    function changedInputsCount() {
        return inputs.filter(function (input) {
            return input.value !== initialValues.get(input);
        }).length;
    }

    function syncSaveState() {
        var count = changedInputsCount();
        var hasChanges = count > 0;
        var text = hasChanges
            ? count + (count === 1 ? ' modification a sauvegarder.' : ' modifications a sauvegarder.')
            : 'Aucune modification en attente.';

        if (status) status.textContent = text;
        if (barText) barText.textContent = text;
        if (bar) {
            bar.classList.toggle('is-visible', hasChanges);
            bar.setAttribute('aria-hidden', hasChanges ? 'false' : 'true');
        }
        document.body.classList.toggle('has-unsaved-changes', hasChanges);
    }

    form.addEventListener('submit', function () {
        isSubmitting = true;
        document.body.classList.remove('has-unsaved-changes');
        if (bar) {
            bar.classList.remove('is-visible');
            bar.setAttribute('aria-hidden', 'true');
        }
    });

    document.addEventListener('keydown', function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
            event.preventDefault();
            if (changedInputsCount() > 0) form.requestSubmit();
            return;
        }

        if (event.key !== 'Enter' || !event.target.matches('[data-grade-input]')) return;
        event.preventDefault();

        var gradeInputs = Array.prototype.slice.call(form.querySelectorAll('[data-grade-input]:not([readonly]):not([disabled])'));
        var columnInputs = gradeInputs.filter(function (input) {
            return input.name === event.target.name;
        });
        var next = columnInputs[columnInputs.indexOf(event.target) + 1];
        if (next) {
            next.focus();
            next.select();
        }
    });

    window.addEventListener('beforeunload', function (event) {
        if (isSubmitting || changedInputsCount() === 0) return;
        event.preventDefault();
        event.returnValue = '';
    });

    syncSaveState();
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

function calculLive(id) {
    updateMoyenne(id, computeActivite(id));
}

function updateActivityTotal(id) {
    var actInput = document.getElementById('act_' + id);
    var total = clampInput(actInput, 20);
    var remaining = total;
    var components = [
        ['part_', 3],
        ['comport_', 6],
        ['cah_', 5],
        ['proj_', 4],
        ['ao_', 2]
    ];

    components.forEach(function (component) {
        var input = document.getElementById(component[0] + id);
        var value = Math.min(component[1], Math.max(0, remaining));
        if (input) input.value = value.toFixed(2);
        remaining -= value;
    });

    if (actInput) actInput.value = total.toFixed(2);
    updateMoyenne(id, total);
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
