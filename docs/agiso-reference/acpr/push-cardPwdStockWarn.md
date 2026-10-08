# 卡密库存预警通知

来源：https://open.agiso.com/document/#/acpr/push/cardPwdStockWarn（2026-10-08 抓取的渲染文本）

卡密库存预警通知

简要描述：  推送示例

￥基础
提卡时触发库存校验，当库存数量小于等于预警数量时，推送预警消息（未再次添加卡密前，24小时内限推送一次）。
推送的签名请务必验证，以验证数据来源的合法性。验证方法参考以下说明。
推送时，有可能消息重复推送。在业务进行之前，对消息进行去重判断，以Tid组合为唯一标识。
推送方式，用jquery做示例：$.post('http://test.com/agiso?timestamp=11222212121&sign=f8aa165fc951f266667e0605d78b93af&aopic=32768', { json: '{"Tid":"592823138",......}' })

推送参数：

参数名	类型	获取方式	说明
fromPlatform
	
string
	
Query/Get
	
参数值：Acpr。常见问题


timestamp
	
Number
	
Query/Get
	
时间戳


aopic
	
Number
	
Query/Get
	
推送类型，1:卡密库存预警通知;


sign
	
String
	
Query/Get
	
签名算法：
   将json和timestamp参数名和参数值组合起来（注意：json在前，timestamp在后），然后前后添加上AppSecret ，再进行Md5加密（加密算法参考接入指南-完整调用API示例代码中MD5算法）。
例：
url：http://test.com/agiso?timestamp=11222212121&sign=f8aa165fc951f266667e0605d78b93af&aopic=256，
postData: { json: {"Tid":2067719225654838,"Status":"WAIT_BUYER_CONFIRM_GOODS",......,"TotalFee":"3.00"} }，
_appsecret: 9f8g9d78sg9d8f8ew9f89ds9f8ds9af8(开发者AppSecret)，
连接后的串: 9f8g9d78sg9d8f8ew9f89ds9f8ds9af8json{"Tid":2067719225654838,"Status":"WAIT_BUYER_CONFIRM_GOODS",......,"TotalFee":"3.00"}timestamp112222121219f8g9d78sg9d8f8ew9f89ds9f8ds9af8
再对连接后的字符串，进行MD5加密，
MD5结果: f8aa165fc951f266667e0605d78b93af（不区分大小写）


json
	
String
	
Form/Post
	
推送消息,如：
{
 "AliasName": "10充值卡别名",    // 卡种别名
 "CpkName": "10充值卡",   // 卡种名称
 "CpkId": 25,    // 卡种Id
 "WarningNum": 50,    // 库存预警值
 "RemainingCount": 45,    // 库存
 "CreateTime": "2022-01-19T10:36:39",    // 触发预警时间
}
