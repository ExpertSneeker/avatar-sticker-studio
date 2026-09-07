export interface PrintSettings {
  paper_width_mm: number; paper_height_mm: number; long_edge_mm: number
  margin_mm: number; gap_mm: number; dpi: number; brightness: boolean; color_balance: boolean
}
export const defaultPrint: PrintSettings = {paper_width_mm:210,paper_height_mm:297,long_edge_mm:85,margin_mm:10,gap_mm:10,dpi:300,brightness:false,color_balance:false}
export interface CreditWallet {available:number;frozen:number;spent:number;version:number;exempt:boolean}
export interface User {can_edit_library?:boolean;generation_concurrency?:number;credits?:CreditWallet;id:string;username:string;display_name:string;role:string;watermark:string;print_defaults:PrintSettings;active?:boolean}
export interface Sticker {id:string;code:string;name:string;category:string;active:boolean;revision:number;image:{id:string;url:string};editable:boolean}
export interface TemplateImage {sticker_id?:string;code?:string;revision?:number;active?:boolean;id:string;url:string;position:number}
export interface TemplateSet {sticker_ids?:string[];available?:boolean;scope?:'public'|'personal';owner?:string|null;editable?:boolean;id:string;code:string;name:string;category:string;active:boolean;revision:number;images:TemplateImage[]}
export interface Item {sticker_id?:string;sticker_code?:string;id:string;set_code:string;position:number;status:string;error:string|null;result_url:string|null;template_url:string;attempt:number;raw_available?:boolean;processing_stage?:'generate'|'postprocess';fal_request_id?:string|null;fal_status?:'IN_QUEUE'|'IN_PROGRESS'|'COMPLETED'|null;queue_position?:number|null;remote_reserved?:boolean;recoverable?:boolean}
export interface Artifact {id:string;path:string;url:string;sha256:string;size:number;kind:string}
export interface Manifest {order_id:string;name:string;version:number;complete:boolean;files:Artifact[]}
export interface ExportEntry {item_id:string;sticker_id:string;code:string;revision:number;source_type:"template"|"sticker";source_id:string;position:number;copy_index:number}
export interface Order {generation_count?:number;export_count?:number;export_entries?:ExportEntry[];client_token?:string;preview_url?:string|null;download_ready?:boolean;id:string;name:string;status:string;created_at:string;total:number;completed:number;failed:number;unknown:number;paused:boolean;avatar_url:string;template_codes:string[];print_settings:PrintSettings;artifact_version:number;items?:Item[];artifacts?:Artifact[];archived?:boolean;processing_error?:string|null}
export interface Settings {max_inflight:number;prompt:string;prompt_version:number;fal_configured:boolean;cutout_configured:boolean}
export interface UploadResult {id:string;offset:number;complete:boolean;filename?:string;url?:string}
export interface Draft {sticker_ids?:string[];output_directory?:FileSystemDirectoryHandle;destination_locked?:boolean;id:string;file:File;name:string;template_ids:string[];print_settings:PrintSettings;upload_id?:string;client_token:string}
