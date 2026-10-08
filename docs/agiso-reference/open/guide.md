# 开放平台的开放平台接入指南

来源：https://open.agiso.com/document/#/open/guide（2026-10-08 抓取的渲染文本）

接入指南
1、接入流程
开放平台托管服务，专为不熟悉开放平台操作流程的商家设计，通过托管模式简化应用创建、信息修改、密钥重置等操作，降低商家使用门槛。
托管服务应用获得商家授权后，可通过本文档接口代商家完成应用全生命周期管理；商家使用电商业务【托管中】应用时，其操作流程与自行创建的电商业务应用完全一致。
(1) 托管服务创建：开发者需先创建托管服务应用。
(2) 托管服务授权：商家将自身开放平台账号授权给该托管服务。
(3) 托管应用创建管理：托管服务为已授权的商家创建对应的电商业务【托管中】应用，并可通过开放平台接口完成应用信息修改、secret 重置等操作。
(4) 商家后台授权：商家获取电商业务【托管中】应用的 AppId，在自身自动发货后台完成授权配置，即可投入使用。
注意事项：
- 单个开放平台账号，可授权给多个托管服务（支持授权给自身申请的托管服务，便于开发调试）。
- 单个托管服务，仅能为每个授权账号创建 1 个电商业务【托管中】应用。
- 电商业务【托管中】应用本质为标准应用，与普通电商业务应用的区别仅在于：支持通过开放平台接口修改数据，其余使用功能完全一致。
- 权限继承规则：电商业务【托管中】应用无需单独向客服申请权限，自动继承对应托管服务的所有接口调用与消息推送权限，仅需为托管服务完成客服侧权限配置。
- 资质简化规则：电商业务【托管中】应用对应的开放平台账号无需进行资质认证。
【开发者操作】登录后台申请AppId。申请时要选择应用类型为【托管服务】
入口：https://open.agiso.com/#/my/application/app-list
【开发者操作】申请到AppId后，开发者可以登录后台管理AppId，这里可以查看和更换AppSecret、更改推送url、更改授权回调url等。
入口：https://open.agiso.com/#/my/application/app-list
【商家操作】授权第三方管理应用：
1、先申请一个开放平台账号。然后登录开放平台。
入口：https://open.agiso.com

2、访问以下页面进行授权
入口：https://open.agiso.com/#/appAuth?appId={$托管服务的AppId}&state={$开发者自定义参数}
【开发者操作】开发者得到各个商家授权给的Token，并使用Token调用接口。调用接口时，需要使用托管服务AppSecret进行签名，具体签名方法参见下文。
注意：开发者与商家，也可以是同一个人。
2、获取AccessToken详解
手动模式自动模式

1、接入流程 

 


          拼接用户授权需访问url ，示例及参数说明如下：
          https://open.agiso.com/#/appAuth?appId={$托管服务的AppId}&state={$开发者自定义参数}
        

 
参数名	必选	类型	说明
appId
	
是
	
long
	
托管服务的AppId


state
	
否
	
string
	
开发者自定义参数，授权回调会把该参数回传回去
 

2、引导用户登录授权

 
          引导用户通过浏览器访问以上授权url
         

3、获取code

 
          用户点“确认”按钮后，Agiso开放平台会将用户重定向到托管服务填写的回调地址上，并附带上 授权码code、自定义参数state 作为参数，应用可以获取并使用该code去换取AccessToken
         

4、换取AccessToken

 
          通过POST调用
          https://open.agiso.com/auth/token?code={$实际获取到的code}&appId={$托管服务的AppId}&sign={$md5后的签名}
          获取AccessToken。换取AccessToken请求参数说明
         
参数名	必选	类型	说明
appId
	
是
	
long
	
托管服务的AppId


code
	
是
	
string
	
上一步从回调地址上获取到的code


sign
	
是
	
string
	
跟接口的签名算法一致，md5({$托管服务的appSecret}appId{$托管服务的AppId}code{$实际获取到的code}{$托管服务的appSecret})
 

换取AccessToken返回值示例

 
{
    "IsSuccess": true,
    "Error_Code": 0,
    "Error_Msg": "",
    "Data": {
        "FromPlatform": "Open",
        "UserId": "sub-d54fca6facc341508c09a420dffb",
        "UserNick": "manage-subapp",
        "ExpiresIn": 2341404360,
        "DeadLine": "2099-12-31 00:00:00",
        "Token": "Openzxgg6shp5nm2dds36dtb4vae8s9dgat2"
    },
    "SuccessCount": 0,
    "FailedCount": 0
}
    
 

换取AccessToken返回参数说明

 
参数名	类型	说明
FromPlatform
	
string
	
参数值：Open。<a href="https://open.agiso.com/document/#/open/faq" target="_blank">常见问题</a>


UserId
	
string
	
用户Id


UserNick
	
string
	
用户昵称


ExpiresIn
	
int
	
AccessToken过期时间（表示 n 秒后过期）


Token
	
string
	
AccessToken
3、调用接口详解
调用任何一个API都必须把AccessToken 和 ApiVersion 添加到Header ,格式为"Authorization: Bearer access_token"，其中Bearer后面有一个空格。同时还需传入以下公共参数：
参数名	必选	类型	说明
timestamp
	
是
	
Date
	
时间戳，例如：1468476350。API服务端允许客户端请求最大时间误差为10分钟。


sign
	
是
	
string
	
API输入参数签名结果,签名算法参照下面的介绍。
注意：接口调用配额，20次/秒。
4、签名算法
【对所有API请求参数（包括公共参数和业务参数，但除去sign参数和byte[]类型的参数），根据参数名称的ASCII码表的顺序排序。如：foo=1, bar=2, foo_bar=3, foobar=4排序后的顺序是bar=2, foo=1, foo_bar=3, foobar=4。
将排序好的参数名和参数值拼装在一起，根据上面的示例得到的结果为：bar2foo1foo_bar3foobar4。
把拼装好的字符串采用utf-8编码，在拼装的字符串前后加上app的secret后，使用MD5算法进行摘要，如：md5({$托管服务的AppSecret}bar2foo1foo_bar3foobar4{$托管服务的AppSecret})
5、Header设置示例代码
JavaC#PHPPython

  HttpPost httpPost = new org.apache.http.client.methods.HttpPost(url);
  httpPost.addHeader("Authorization","Bearer "+ accessToken);
  httpPost.addHeader("ApiVersion", "1");
6、签名算法示例代码
JavaC#PHPPython
 
  Map<String, String> data = new HashMap<String, String>();
  data.put("modifyTimeStart", "2016-07-13 10:44:30");
  data.put("pageNo", "1");
  data.put("pageSize", "20");
  //timestamp 为调用Api的公共参数，详细说明参考接入指南
  data.put("timestamp", '1468476350');//假设当前时间为2016/7/14 14:5:50
  //对键排序
  String[] keys = data.keySet().toArray(new String[0]);
  Arrays.sort(keys);
  StringBuilder query = new StringBuilder();
  //头加入AppSecret ，假设AppSecret值为******************
  query.append(this.getClientSecret());
  for (String key : keys) {
      String value = data.get(key);
      query.append(key).append(value);
  }
  //到这query的值为******************modifyTimeStart2016-07-13 10:44:30pageNo1pageSize20timestamp1468476350
  //尾加入AppSecret
  query.append(this.getClientSecret()); //query=******************modifyTimeStart2016-07-13 10:44:30pageNo1pageSize20timestamp1468476350******************
  byte[] md5byte = encryptMD5(query.toString());
  //sign 为调用Api的公共参数，详细说明参考接入指南
  data.put("sign", byte2hex(md5byte)); //byte2hex(md5byte) = 935671331572EBF7F419EBB55EA28558
  
  // Md5摘要
  public byte[] encryptMD5(String data) throws NoSuchAlgorithmException, UnsupportedEncodingException {
      MessageDigest md5 = MessageDigest.getInstance("MD5");
      return md5.digest(data.getBytes("UTF-8"));
  }

  public String byte2hex(byte[] bytes) {
      StringBuilder sign = new StringBuilder();
      for (int i = 0; i < bytes.length; i++) {
          String hex = Integer.toHexString(bytes[i] & 0xFF);
          if (hex.length() == 1) {
              sign.append("0");
          }
          sign.append(hex.toLowerCase());
      }
      return sign.toString();
  }
7、完整调用API示例代码
以下代码以调用LogisticsDummySend(更新发货状态)为例
JavaC#PHPPython

  public String logisticsDummySend() {
      String appSecret = "******************";
      String accessToken = "*************************";

      CloseableHttpClient httpclient = HttpClients.createDefault();
      HttpPost httpPost = new HttpPost("https://gw-api.agiso.com/open/Trade/LogisticsDummySend");
      // 设置头部
      httpPost.addHeader("Authorization", "Bearer " + accessToken);
      httpPost.addHeader("ApiVersion", "1");
      //业务参数
      Map<String, String> data = new HashMap<String, String>();
      String tids = "1234567789,9874561233";
      data.put("tids", tids); 注意 tids是示例参数实际参数要以当前文档上的入参为准！！！
      Long timestamp = System.currentTimeMillis() / 1000;
      data.put("timestamp", timestamp.toString());
      // 参数签名
      try {
          data.put("sign", sign(data, appSecret));
      } catch (NoSuchAlgorithmException e) {
          e.printStackTrace();
      } catch (UnsupportedEncodingException e) {
          e.printStackTrace();
      }
      List<BasicNameValuePair> params = new ArrayList<BasicNameValuePair>();
      for (Map.Entry<String, String> entry : data.entrySet()) {
          params.add(new BasicNameValuePair(entry.getKey(), entry.getValue()));
      }
      // 发起POST请求
      try {
          httpPost.setEntity(new UrlEncodedFormEntity(params, "UTF-8"));
          HttpResponse httpResponse = httpclient.execute(httpPost);
          if (httpResponse.getStatusLine().getStatusCode() == HttpStatus.SC_OK) {
              return EntityUtils.toString(httpResponse.getEntity());
          } else {
              return ("doPost Error Response: " + httpResponse.getStatusLine().toString());
          }
      } catch (Exception e) {
          e.printStackTrace();
          return null;
      }
  }

  // 参数签名
  public String sign(Map<String, String> params, String appSecret)
          throws NoSuchAlgorithmException, UnsupportedEncodingException {
      String[] keys = params.keySet().toArray(new String[0]);
      Arrays.sort(keys);

      StringBuilder query = new StringBuilder();
      query.append(appSecret);
      for (String key : keys) {
          String value = params.get(key);
          query.append(key).append(value);
      }
      query.append(appSecret);

      byte[] md5byte = encryptMD5(query.toString());

      return byte2hex(md5byte);
  }

  // byte数组转成16进制字符串
  public static String byte2hex(byte[] bytes) {
      StringBuilder sign = new StringBuilder();
      for (int i = 0; i < bytes.length; i++) {
          String hex = Integer.toHexString(bytes[i] & 0xFF);
          if (hex.length() == 1) {
              sign.append("0");
          }
          sign.append(hex.toLowerCase());
      }
      return sign.toString();
  }

  // Md5摘要
  public static byte[] encryptMD5(String data) throws NoSuchAlgorithmException, UnsupportedEncodingException {
      MessageDigest md5 = MessageDigest.getInstance("MD5");
      return md5.digest(data.getBytes("UTF-8"));
  }

## 标签页：手动模式

暂不支持手动模式
