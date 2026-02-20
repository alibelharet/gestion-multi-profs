import os

filepath = r"c:\Users\21379\OneDrive\Bureau\Gestion_Multi_Profs\templates\stats.html"

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Part 1: Header replacement
old_header = """<div class="app-card hero-card mb-4 p-3">
    <div class="d-flex flex-wrap justify-content-between align-items-center gap-3">
        <div>
            <div class="text-uppercase small text-muted">Statistiques</div>
            <h2 class="fw-bold mb-1">Détails & Évolution</h2>
            <div class="text-muted small">Analyse approfondie par matière</div>
        </div>
        <div class="d-flex align-items-center gap-2">
            <form action="{{ url_for('dashboard.stats') }}" method="get" class="d-flex gap-2">
                {% if session.get('is_admin') %}
                <select name="school_year" class="form-select form-select-sm" onchange="this.form.submit()">
                    {% for sy in school_years %}
                    <option value="{{ sy.label }}" {% if school_year==sy.label %}selected{% endif %}>
                        {{ sy.label }}{% if sy.is_active %} (active){% endif %}
                    </option>
                    {% endfor %}
                </select>
                {% else %}
                <input type="hidden" name="school_year" value="{{ school_year }}">
                {% endif %}
                <select name="subject" class="form-select form-select-sm" onchange="this.form.submit()">
                    {% for s in subjects %}
                    <option value="{{ s.id }}" {% if subject_id==s.id %}selected{% endif %}>{{ s.name }}</option>
                    {% endfor %}
                </select>
            </form>
        </div>
    </div>
</div>"""

new_header = """<div class="app-card hero-card mb-4 p-3">
    <div class="d-flex flex-wrap justify-content-between align-items-center gap-3">
        <div>
            <div class="text-uppercase small text-muted">Statistiques</div>
            <h2 class="fw-bold mb-1">Détails & Évolution</h2>
            <div class="text-muted small">Analyse approfondie par matière</div>
        </div>
        <div class="d-flex align-items-center gap-2">
            <a href="{{ url_for('reports.export_stats_pdf', trimestre=trimestre, subject=subject_id, school_year=school_year, niveau=niveau_actuel) }}" class="btn btn-sm btn-danger text-white">
                <i class="bi bi-file-pdf-fill me-1"></i> Télécharger PDF
            </a>
            <form action="{{ url_for('dashboard.stats') }}" method="get" class="d-flex gap-2">
                {% if session.get('is_admin') %}
                <select name="school_year" class="form-select form-select-sm" onchange="this.form.submit()">
                    {% for sy in school_years %}
                    <option value="{{ sy.label }}" {% if school_year==sy.label %}selected{% endif %}>
                        {{ sy.label }}{% if sy.is_active %} (active){% endif %}
                    </option>
                    {% endfor %}
                </select>
                {% else %}
                <input type="hidden" name="school_year" value="{{ school_year }}">
                {% endif %}
                <select name="trimestre" class="form-select form-select-sm" onchange="this.form.submit()">
                    <option value="1" {% if trimestre=='1' %}selected{% endif %}>T1</option>
                    <option value="2" {% if trimestre=='2' %}selected{% endif %}>T2</option>
                    <option value="3" {% if trimestre=='3' %}selected{% endif %}>T3</option>
                </select>
                <select name="niveau" class="form-select form-select-sm" onchange="this.form.submit()">
                    <option value="all">Toutes les classes</option>
                    {% for classe in liste_classes %}
                    <option value="{{ classe }}" {% if niveau_actuel==classe %}selected{% endif %}>{{ classe }}</option>
                    {% endfor %}
                </select>
                <select name="subject" class="form-select form-select-sm" onchange="this.form.submit()">
                    {% for s in subjects %}
                    <option value="{{ s.id }}" {% if subject_id==s.id %}selected{% endif %}>{{ s.name }}</option>
                    {% endfor %}
                </select>
            </form>
        </div>
    </div>
</div>

<div class="row g-3 mb-4 animate-fade-up">
    <div class="col-6 col-md-3">
        <div class="app-card p-3 h-100 text-center">
            <div class="text-muted small">Moyenne générale</div>
            <h3 class="fw-bold text-primary">{{ stats.moyenne_generale }}</h3>
        </div>
    </div>
    <div class="col-6 col-md-3">
        <div class="app-card p-3 h-100 text-center">
            <div class="text-muted small">Taux de réussite</div>
            <h3 class="fw-bold text-success">{{ stats.taux_reussite }}%</h3>
        </div>
    </div>
    <div class="col-6 col-md-3">
        <div class="app-card p-3 h-100 text-center">
            <div class="text-muted small">Admis / Total</div>
            <h3 class="fw-bold text-body">{{ stats.nb_admis }} / {{ stats.nb_total }}</h3>
        </div>
    </div>
    <div class="col-6 col-md-3">
        <div class="app-card p-3 h-100 text-center">
            <div class="text-muted small">Max / Min</div>
            <h3 class="fw-bold text-body">{{ stats.meilleure_note }} / {{ stats.pire_note }}</h3>
        </div>
    </div>
</div>

<div class="app-card mb-4 animate-fade-up">
    <div class="card-header app-card-header d-flex justify-content-between align-items-center py-2 px-3 rounded-top">
        <h6 class="mb-0 text-body">Statistiques Avancées T{{ trimestre }}</h6>
    </div>
    <div class="card-body">
        <div class="row g-3">
            <div class="col-12 col-lg-6">
                <div class="text-muted small mb-2 text-center">Moyenne par classe</div>
                <canvas id="chartClasses" height="200"></canvas>
            </div>
            <div class="col-12 col-lg-6">
                <div class="text-muted small mb-2 text-center">Répartition des notes</div>
                <canvas id="chartDist" height="200"></canvas>
            </div>
        </div>
    </div>
</div>"""

content = content.replace(old_header, new_header)

# Part 2: Top students table
old_top = """<div class="row g-4">
    <!-- Graphique Évolution -->
    <div class="col-12 col-lg-8">
        <div class="app-card h-100">
            <div class="card-header app-card-header py-3 px-4 border-bottom">
                <h6 class="mb-0 fw-bold">Évolution des Moyennes par Classe (T1 à T3)</h6>
            </div>
            <div class="card-body p-4">
                <canvas id="evolutionChart" style="max-height: 400px;"></canvas>
            </div>
        </div>
    </div>

    <!-- Top Élèves -->
    <div class="col-12 col-lg-4">
        <div class="app-card h-100">
            <div class="card-header app-card-header py-3 px-4 border-bottom">
                <h6 class="mb-0 fw-bold">Top 5 Élèves (Annuel)</h6>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="bg-light">
                            <tr>
                                <th class="ps-4">Élève</th>
                                <th class="text-center">Classe</th>
                                <th class="text-center fw-bold text-primary">Moy. An</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for eleve in top_students %}
                            <tr>
                                <td class="ps-4">
                                    <div class="fw-bold">{{ eleve.nom }}</div>
                                    <div class="small text-muted">
                                        <span class="badgex bg-light text-secondary border rounded px-1">T1: {{ eleve.t1
                                            }}</span>
                                        <span class="badgex bg-light text-secondary border rounded px-1">T2: {{ eleve.t2
                                            }}</span>
                                        <span class="badgex bg-light text-secondary border rounded px-1">T3: {{ eleve.t3
                                            }}</span>
                                    </div>
                                </td>
                                <td class="text-center"><span class="badge bg-secondary">{{ eleve.niveau }}</span></td>
                                <td class="text-center fw-bold fs-5 text-primary">{{ eleve.annual }}</td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="3" class="text-center py-4 text-muted">Aucune donnée disponible</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>"""

new_top = """<div class="row g-4 mb-4">
    <!-- Graphique Évolution -->
    <div class="col-12 col-lg-8">
        <div class="app-card h-100">
            <div class="card-header app-card-header py-3 px-4 border-bottom">
                <h6 class="mb-0 fw-bold">Évolution des Moyennes par Classe (T1 à T3)</h6>
            </div>
            <div class="card-body p-4">
                <canvas id="evolutionChart" style="max-height: 350px;"></canvas>
            </div>
        </div>
    </div>

    <!-- Top Élèves -->
    <div class="col-12 col-lg-4">
        <div class="app-card h-100">
            <div class="card-header app-card-header py-3 px-4 border-bottom">
                <h6 class="mb-0 fw-bold">Top 5 Élèves (Annuel)</h6>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="bg-light">
                            <tr>
                                <th class="ps-4">Élève</th>
                                <th class="text-center">Classe</th>
                                <th class="text-center fw-bold text-primary">Moy. An</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for eleve in top_students %}
                            <tr>
                                <td class="ps-4">
                                    <div class="fw-bold">{{ eleve.nom }}</div>
                                    <div class="small text-muted">
                                        <span class="badgex border rounded px-1">T1: {{ eleve.t1 }}</span>
                                        <span class="badgex border rounded px-1">T2: {{ eleve.t2 }}</span>
                                        <span class="badgex border rounded px-1">T3: {{ eleve.t3 }}</span>
                                    </div>
                                </td>
                                <td class="text-center"><span class="badge bg-secondary">{{ eleve.niveau }}</span></td>
                                <td class="text-center fw-bold fs-5 text-primary">{{ eleve.annual }}</td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="3" class="text-center py-4 text-muted">Aucune donnée disponible</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>

<div class="row g-4 mb-4">
    <div class="col-12 col-lg-6">
        <div class="app-card h-100">
            <div class="card-header app-card-header py-3 px-4 border-bottom">
                <h6 class="mb-0 fw-bold">Top Élèves T{{ trimestre }}</h6>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="bg-light">
                            <tr>
                                <th class="ps-4">#</th>
                                <th>Élève</th>
                                <th>Classe</th>
                                <th class="text-center">Moyenne</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for e in top_eleves %}
                            <tr>
                                <td class="ps-4 text-muted">{{ loop.index }}</td>
                                <td class="fw-bold">{{ e.nom }}</td>
                                <td><span class="badge bg-secondary">{{ e.niveau }}</span></td>
                                <td class="text-center fw-bold text-success">{{ e.moyenne }}</td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="4" class="text-center py-4 text-muted">Aucun résultat</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    
    <div class="col-12 col-lg-6">
        <div class="app-card h-100 border-danger border-opacity-25">
            <div class="card-header app-card-header py-3 px-4 border-bottom d-flex justify-content-between align-items-center">
                <h6 class="mb-0 fw-bold text-danger"><i class="bi bi-exclamation-triangle-fill me-2"></i>Élèves à Risque T{{ trimestre }}</h6>
                <span class="badge bg-danger rounded-pill">{{ risk_count }}</span>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0 align-middle">
                        <thead class="bg-light">
                            <tr>
                                <th class="ps-4">Élève</th>
                                <th>Classe</th>
                                <th class="text-center">Moyenne</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for e in risk_students %}
                            <tr>
                                <td class="ps-4 fw-bold">{{ e.nom }}</td>
                                <td><span class="badge bg-secondary">{{ e.niveau }}</span></td>
                                <td class="text-center fw-bold text-danger">{{ e.moyenne }}</td>
                                <td class="text-end pe-4">
                                    <a href="/bulletin/{{ e.id }}?trimestre={{ trimestre }}&subject={{ subject_id }}&school_year={{ school_year }}"
                                        target="_blank" class="btn btn-sm btn-outline-secondary py-0"><i class="bi bi-file-text"></i></a>
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="4" class="text-center py-4 text-muted">Aucun élève en difficulté.</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% if risk_count > 8 %}
                <div class="card-footer text-center bg-transparent">
                    <a href="{{ risk_url }}" class="small text-danger text-decoration-none">Voir les {{ risk_count }} élèves</a>
                </div>
                {% endif %}
            </div>
        </div>
    </div>
</div>"""

content = content.replace(old_top, new_top)

# Part 3: JS Scripts
old_js = """    document.addEventListener('DOMContentLoaded', function () {
        const ctx = document.getElementById('evolutionChart').getContext('2d');

        const data = {{ evolution | tojson
    }};

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: 'Trimestre 1',
                    data: data.t1,
                    backgroundColor: 'rgba(54, 162, 235, 0.7)',
                    borderColor: 'rgb(54, 162, 235)',
                    borderWidth: 1
                },
                {
                    label: 'Trimestre 2',
                    data: data.t2,
                    backgroundColor: 'rgba(75, 192, 192, 0.7)',
                    borderColor: 'rgb(75, 192, 192)',
                    borderWidth: 1
                },
                {
                    label: 'Trimestre 3',
                    data: data.t3,
                    backgroundColor: 'rgba(255, 99, 132, 0.7)',
                    borderColor: 'rgb(255, 99, 132)',
                    borderWidth: 1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    max: 20
                }
            },
            plugins: {
                legend: {
                    position: 'bottom'
                }
            }
        }
    });
    });"""

new_js = """    document.addEventListener('DOMContentLoaded', function () {
        // Data for annual evolution
        const evolutionData = {{ evolution | tojson }};
        const ctxEvol = document.getElementById('evolutionChart').getContext('2d');
        new Chart(ctxEvol, {
            type: 'bar',
            data: {
                labels: evolutionData.labels,
                datasets: [
                    { label: 'T1', data: evolutionData.t1, backgroundColor: 'rgba(54, 162, 235, 0.7)' },
                    { label: 'T2', data: evolutionData.t2, backgroundColor: 'rgba(75, 192, 192, 0.7)' },
                    { label: 'T3', data: evolutionData.t3, backgroundColor: 'rgba(255, 99, 132, 0.7)' }
                ]
            },
            options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, max: 20 } } }
        });

        // Data for T current advanced stats
        const chartData = {{ chart_data | tojson | safe }};
        
        if (chartData && chartData.classes && chartData.classes.labels.length > 0) {
            new Chart(document.getElementById('chartClasses'), {
                type: 'bar',
                data: {
                    labels: chartData.classes.labels,
                    datasets: [{
                        label: 'Moyenne T{{ trimestre }}',
                        data: chartData.classes.values,
                        backgroundColor: 'rgba(47, 123, 255, 0.6)',
                        borderColor: 'rgb(47, 123, 255)',
                        borderWidth: 1
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, max: 20 } } }
            });
        }
        
        if (chartData && chartData.distribution && chartData.distribution.values.some(v => v > 0)) {
            new Chart(document.getElementById('chartDist'), {
                type: 'doughnut',
                data: {
                    labels: chartData.distribution.labels,
                    datasets: [{
                        data: chartData.distribution.values,
                        backgroundColor: ['#198754', '#dc3545', '#6c757d']
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false, cutout: '70%', plugins: { legend: { position: 'right' } } }
            });
        }
    });"""

content = content.replace(old_js, new_js)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated successfully")
