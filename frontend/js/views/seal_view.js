export const sealViewTemplate = `
<section class="panel">
  <h2>封批升代</h2>
  <p class="hint">校准有效、无开放游标、无解冻待提交时方可封批；解冻轨只登记，不写封批正式字段。</p>
  <div class="form-row">
    <div><label>批次</label>
      <select v-model.number="sealForm.batch_id"><option v-for="b in sealableBatches" :key="b.id" :value="b.id">{{ b.batch_code }}</option></select>
    </div>
    <div><label>快照附言</label><input v-model="sealForm.manifest"/></div>
  </div>
  <div class="actions"><button @click="doSeal">执行封批</button></div>
  <div v-if="shadowBatches.length" class="detail-box">
    <h3>影子封批态（未晋升，不展示为已封）</h3>
    <ul>
      <li v-for="b in shadowBatches" :key="b.id">
        {{ b.batch_code }} · {{ b.state.seal_track }} · 解冻待提交 {{ b.state.thaw_pending }} · {{ trackBadge(b) }}
      </li>
    </ul>
  </div>
  <table class="data-table">
    <thead><tr><th>批次</th><th>代</th><th>封批轨</th><th>解冻轨</th><th>封批时间</th><th>附言摘要</th></tr></thead>
    <tbody>
      <tr v-for="s in seals" :key="s.id">
        <td>{{ s.batch_code }}</td>
        <td>{{ s.batch_generation }}</td>
        <td>{{ s.state ? s.state.seal_track : "—" }}</td>
        <td>{{ s.state ? s.state.thaw_track : "—" }}</td>
        <td>{{ s.sealed_at }}</td>
        <td>{{ shortText(s.manifest) }}</td>
      </tr>
    </tbody>
  </table>
</section>
`;
