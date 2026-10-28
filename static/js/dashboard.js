/* Grade editor: preserve drafts on error, send only changed rows, never overwrite stale versions. */
(function () {
'use strict';
const form = document.getElementById('formSaveAll');
if (!form) return;
const text = window.gradeText;
const rows = Array.from(form.querySelectorAll('[data-grade-row]'));
const canEdit = form.dataset.canEdit === 'true';
const status = document.getElementById('saveStatus');
const errorBox = document.getElementById('saveError');
const bar = document.getElementById('unsavedChangesBar');
const buttons = Array.from(form.querySelectorAll('[data-save-button]'));
const initial = new Map();
let timer, saving = false, error = false, queueSave = false;
let active = 0;
function values(row) {
    return {id: Number(row.dataset.studentId), version: Number(row.querySelector('[name="version"]').value),
        activite: row.querySelector('[name="activite"]').value,
        devoir: row.querySelector('[name="devoir"]').value,
        compo: row.querySelector('[name="compo"]').value,
        status: row.querySelector('[name="status"]').value};
}
function signature(row) { const {version, ...data} = values(row); return JSON.stringify(data); }
function changed() { return rows.filter(row => signature(row) !== initial.get(row)); }
function refreshRow(row, hideRemark = false) {
    const data = values(row);
    const inputs = Array.from(row.querySelectorAll('[data-grade-input]'));
    const valid = inputs.every(input => input.validity.valid);
    const filled = inputs.filter(input => input.value !== '').length;
    const state = data.status === 'absent' ? 'absent' : filled === 3 && valid ? 'graded' : filled ? 'partial' : 'not_entered';
    row.querySelector('[data-assessment-label]').textContent = text[state];
    row.dataset.assessment = state;
    row.classList.toggle('grade-row-incomplete', state === 'partial' || state === 'not_entered');
    const average = row.querySelector('[data-average]');
    average.textContent = state === 'graded' ? (((Number(data.activite) + Number(data.devoir))/2 + Number(data.compo)*2)/3).toFixed(2) : '—';
    average.className = state === 'graded' ? (Number(average.textContent) < 10 ? 'text-danger' : 'text-success') : 'text-muted';
    if (state !== 'graded' || hideRemark) row.querySelector('[data-remark]').textContent = '';
}
function updateState() {
    const dirty = changed().length;
    if (bar) bar.hidden = !dirty;
    document.body.classList.toggle('has-unsaved-changes', !!dirty);
    const barText = document.getElementById('unsavedChangesText');
    if (barText) barText.textContent = text.pending + ' · ' + dirty;
    if (!saving && !error) status.textContent = dirty ? text.pending : text.idle;
    buttons.forEach(button => { button.disabled = saving; button.setAttribute('aria-busy', String(saving)); });
    const complete = rows.filter(row => row.dataset.assessment === 'graded').length;
    document.getElementById('gradeCompletionStatus').textContent = text.completion + ': ' + complete + ' / ' + rows.length;
}
function schedule() {
    clearTimeout(timer);
    if (!error && canEdit) timer = setTimeout(save, 1500);
}
async function save() {
    clearTimeout(timer);
    if (saving) { queueSave = true; return; }
    const dirty = changed();
    if (!dirty.length || !canEdit) return;
    if (!form.checkValidity()) {
        error = true; errorBox.hidden = false; errorBox.textContent = text.invalid; status.textContent = text.invalid;
        const invalidRow = rows.find(row => row.querySelector('input:invalid'));
        if (invalidRow) { active = rows.indexOf(invalidRow); showStudent(); }
        form.reportValidity(); return;
    }
    const sent = dirty.map(row => ({row, data: values(row), signature: signature(row)}));
    saving = true; error = false; errorBox.hidden = true;
    status.textContent = text.saving; updateState();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
        const response = await fetch(form.action, {
            method:'POST', credentials:'same-origin', signal:controller.signal,
            headers:{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token':form.querySelector('[name="csrf_token"]').value},
            body:JSON.stringify({trimestre_save:form.querySelector('[name="trimestre_save"]').value,
                subject:form.querySelector('[name="subject"]').value, school_year:form.querySelector('[name="school_year"]').value,
                rows:sent.map(item => item.data)})
        });
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error(text.error);
        const data = await response.json();
        if (!response.ok) {
            if (data.error === 'conflict') document.getElementById('compareCurrent').hidden = false;
            const row = rows.find(row => Number(row.dataset.studentId) === data.student_id);
            if (row) { active=rows.indexOf(row); showStudent(); row.classList.add('grade-error-row'); }
            throw new Error(data.message || text.error);
        }
        if (!Array.isArray(data.saved) || data.saved.length !== sent.length) throw new Error(text.error);
        for (const item of sent) {
            const result = data.saved.find(result => result.id === item.data.id);
            if (!result || !Number.isInteger(result.version)) throw new Error(text.error);
            item.row.querySelector('[name="version"]').value = result.version;
            initial.set(item.row, item.signature);
            item.row.classList.remove('grade-error-row');
            item.row.querySelector('.legacy-note')?.remove();
            if (signature(item.row) === item.signature) item.row.querySelector('[data-remark]').textContent = result.remark || '';
        }
        document.getElementById('metricsHint').textContent = text.refreshStats;
        status.textContent = text.saved + ' · ' + new Date().toLocaleTimeString(document.documentElement.lang, {hour:'2-digit',minute:'2-digit'});
    } catch (failure) {
        error = true; errorBox.hidden = false; errorBox.textContent = failure.message === 'The user aborted a request.' ? text.error : (failure.message || text.error);
        status.textContent = text.error;
    } finally {
        clearTimeout(timeout); saving = false;
        const savedMessage = status.textContent;
        updateState();
        if (!error && !changed().length) status.textContent = savedMessage;
        if (!error && (queueSave || changed().length)) schedule();
        queueSave = false;
    }
}
rows.forEach(row => { initial.set(row, signature(row)); refreshRow(row); });
if (canEdit) {
    form.addEventListener('input', event => {
        const row = event.target.closest('[data-grade-row]');
        if (!row || !event.target.matches('[data-grade-input], [name="status"]')) return;
        refreshRow(row, true); error=false; errorBox.hidden=true; updateState(); schedule();
    });
    form.addEventListener('change', event => {
        if (event.target.name === 'status') { refreshRow(event.target.closest('[data-grade-row]'), true); error=false; updateState(); schedule(); }
    });
    form.addEventListener('submit', event => { event.preventDefault(); save(); });
    document.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save(); }
        if (event.key === 'Enter' && event.target.matches('[data-grade-input]')) {
            event.preventDefault();
            const index = rows.indexOf(event.target.closest('[data-grade-row]')) + (event.shiftKey ? -1 : 1);
            if (rows[index]) { active=index; showStudent(); const input=rows[index].querySelector('[name="'+event.target.name+'"]'); input.focus(); input.select(); }
        }
    });
    window.addEventListener('beforeunload', event => {
        if (changed().length || saving) { event.preventDefault(); event.returnValue=''; }
    });
}
const phone = window.matchMedia('(max-width: 700px)');
const picker = document.getElementById('studentPicker');
function showStudent() {
    const deleting = document.getElementById('studentsTableContainer').classList.contains('delete-mode');
    form.classList.toggle('student-mode', phone.matches && !deleting);
    document.querySelector('.student-pager').hidden = !phone.matches || deleting || !rows.length;
    rows.forEach((row,index) => row.classList.toggle('current-student', index === active));
    picker.value=String(active);
    document.getElementById('previousStudent').disabled=active<=0;
    document.getElementById('nextStudent').disabled=active>=rows.length-1;
}
picker.addEventListener('change', () => {active=Number(picker.value); showStudent();});
document.getElementById('previousStudent').addEventListener('click', () => {active=Math.max(0,active-1);showStudent();});
document.getElementById('nextStudent').addEventListener('click', () => {active=Math.min(rows.length-1,active+1);showStudent();});
phone.addEventListener('change',showStudent); showStudent(); updateState();
window.setDeleteMode = enabled => {
    if (enabled && (changed().length || saving)) { alert(text.saveFirst); return; }
    document.getElementById('studentsTableContainer').classList.toggle('delete-mode',enabled);
    document.getElementById('deleteModeToolbar')?.classList.toggle('d-none',!enabled);
    if (!enabled) document.querySelectorAll('.check-delete,.select-all-delete').forEach(input=>{input.checked=false;input.indeterminate=false;});
    window.syncDeleteSelectionState();showStudent();
};
window.enterDeleteMode = event => { event?.preventDefault(); window.setDeleteMode(true); return false; };
window.syncDeleteSelectionState = () => {
    const checked = document.querySelectorAll('.check-delete:checked').length;
    const count=document.getElementById('deleteSelectionCount');if(count)count.textContent=checked+' '+text.selected;
    const btn=document.getElementById('deleteSelectedBtn');if(btn)btn.disabled=!checked;
    const all=document.querySelector('.select-all-delete');if(all){all.checked=checked>0&&checked===rows.length;all.indeterminate=checked>0&&checked<rows.length;}
};
window.toggle = source => {document.querySelectorAll('.check-delete').forEach(input=>input.checked=source.checked);window.syncDeleteSelectionState();};
window.submitDelete = () => {
    if (changed().length || saving) {alert(text.saveFirst);return;}
    const selected=Array.from(document.querySelectorAll('.check-delete:checked'));
    if(!selected.length || !confirm(text.trashConfirm))return;
    const target=document.getElementById('formMultiDelete');target.querySelectorAll('[name="ids"]').forEach(input=>input.remove());
    selected.forEach(checkbox=>{const input=document.createElement('input');input.type='hidden';input.name='ids';input.value=checkbox.value;target.append(input);});
    target.requestSubmit();
};
window.printStudentList = () => {
    const popup=window.open('','_blank');if(!popup)return;
    const doc=popup.document;doc.title=text.printTitle;doc.documentElement.lang=document.documentElement.lang;doc.documentElement.dir=document.documentElement.dir;
    const heading=doc.createElement('h1');heading.textContent=text.printTitle;doc.body.append(heading);
    const table=doc.createElement('table');table.style.cssText='width:100%;border-collapse:collapse;font:14px Arial';
    const head=doc.createElement('tr');['#',text.name,text.class].forEach(value=>{const th=doc.createElement('th');th.textContent=value;head.append(th);});table.append(head);
    rows.forEach((row,index)=>{const tr=doc.createElement('tr');[index+1,row.querySelector('.student-fullname').textContent,row.querySelector('.student-name-cell bdi').textContent].forEach(value=>{const td=doc.createElement('td');td.textContent=value;td.style.cssText='border:1px solid #999;padding:6px';tr.append(td);});table.append(tr);});
    doc.body.append(table);popup.print();
};
})();
