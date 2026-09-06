let connection:Promise<IDBDatabase>|undefined
function db() {
  return connection ??= new Promise<IDBDatabase>((resolve,reject)=>{
    const request=indexedDB.open('avatar-stickers-v1',1)
    request.onupgradeneeded=()=>request.result.createObjectStore('state')
    request.onsuccess=()=>resolve(request.result)
    request.onerror=()=>reject(request.error)
  })
}
export async function readLocal<T>(key:string):Promise<T|undefined> {
  const database=await db()
  return new Promise((resolve,reject)=>{
    const request=database.transaction('state').objectStore('state').get(key)
    request.onsuccess=()=>resolve(request.result)
    request.onerror=()=>reject(request.error)
  })
}
export async function writeLocal(key:string,value:unknown) {
  const database=await db()
  return new Promise<void>((resolve,reject)=>{
    const transaction=database.transaction('state','readwrite')
    transaction.objectStore('state').put(value,key)
    transaction.oncomplete=()=>resolve()
    transaction.onerror=()=>reject(transaction.error)
  })
}
