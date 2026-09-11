import { safeFilename } from './sync'
import type { CustomerOrder } from './customer-orders'
export function orderFolderName(order:Pick<CustomerOrder,'order_number'|'notes'>):string {
  let value=(order.order_number+(order.notes?'_'+order.notes:'')).normalize('NFC').replace(/[\\/:*?"<>|\x00-\x1f\x7f]/g,'_').replace(/[. ]+$/g,'').trim()
  const encoder=new TextEncoder();let clipped=''
  for(const character of value){if(encoder.encode(clipped+character).length>210)break;clipped+=character}
  value=clipped.replace(/[. ]+$/g,'')
  if(!safeFilename(value))value='订单_'+(value||'未命名')
  return value
}
export const customerManifestPath=(id:string)=>'/customer-orders/'+encodeURIComponent(id)+'/manifest'
export const customerZipUrl=(id:string)=>'/api/customer-orders/'+encodeURIComponent(id)+'/download.zip'
