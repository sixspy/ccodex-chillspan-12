export const spectrumViewTemplate = `
<section class="panel">
  <h2>温谱导出</h2>
  <p class="hint">仅正式封批（有同代封批快照）可导出；影子封批态与同代重复导出均拒绝。</p>
  <div class="form-row">
    <div><label>正式封批批次</label>
      <select v-model.number="spectrumForm.batch_id"><option v-for="b in sealedBatches" :key="b.id" :value="b.id">{{ b.batch_code }} G{{ b.generation }}</option></select>
    </div>
  </div>
  <div class="actions"><button @click="doSpectrum">导出温谱</button></div>
  <table class="data-table">
    <thead><tr><th>导出号</th><th>批次</th><th>点数</th><th>校验</th><th>封批轨</th><th>解冻轨</th><th>状态</th></tr></thead>
    <tbody>
      <tr v-for="x in spectrumExports" :key="x.id">
        <td>{{ x.export_ref }}</td>
        <td>{{ x.batch_code }}</td>
        <td>{{ x.point_count }}</td>
        <td class="mono">{{ x.checksum }}</td>
        <td>{{ x.state ? x.state.seal_track : "—" }}</td>
        <td>{{ x.state ? x.state.thaw_track : "—" }}</td>
        <td>{{ x.status }}</td>
      </tr>
    </tbody>
  </table>
</section>
`;