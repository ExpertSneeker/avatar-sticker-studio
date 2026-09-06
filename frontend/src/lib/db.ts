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
/** One read/write transaction makes submission destinations immutable across tabs. */
export async function readOrCreateLocal<T>(key:string,value:T):Promise<T> {
  const database=await db()
  return new Promise((resolve,reject)=>{
    const transaction=database.transaction('state','readwrite'),store=transaction.objectStore('state')
    const request=store.get(key)
    let result:T
    request.onsuccess=()=>{result=request.result===undefined?value:request.result;if(request.result===undefined)store.put(value,key)}
    transaction.oncomplete=()=>resolve(result)
    transaction.onerror=()=>reject(transaction.error)
    transaction.onabort=()=>reject(transaction.error||new Error('本机存储事务已取消'))
  })
}
