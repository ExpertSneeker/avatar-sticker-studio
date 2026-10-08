# 拼多多自动发货接入指南

来源：https://open.agiso.com/document/#/aldsPdd/guide（2026-10-08 抓取的渲染文本）

接入指南
1、接入流程
【开发者操作】登录后台申请AppIds。
入口：https://open.agiso.com/#/my/application/app-list
【开发者操作】申请到AppId后，开发者可以登录后台管理AppId，这里可以查看和更换AppSecret、更改推送url、更改授权回调url等。
入口：https://open.agiso.com/#/my/application/app-list
【商家操作】授权，方法有二：
1、输入开发者提供的AppId（相当于告诉Agiso，允许这个AppId通过Agiso开放平台获取或操作商家自己的订单数据），勾选相应要授权的权限。授权后会显示一个Token，将Token复制给开发者。
入口：https://aldsPdd.agiso.com/#/open/authorize
2、开发者如果有开发自动授权，则商家可以通过访问以下页面进行授权：
入口：https://aldsPdd.agiso.com/#/authorize?appId={$开发者应用的AppId}&state={$开发者自定义参数}
【开发者操作】开发者得到各个商家授权给的Token，并使用Token调用接口。调用接口时，需要使用AppSecret进行签名，具体签名方法参见下文。
注意：开发者与商家，也可以是同一个人。
2、获取AccessToken详解
手动模式自动模式
将你的AppId告诉您的用户，用户通过在授权页面(https://aldsPdd.agiso.com/#/open/authorize)进行授权。
          用户授权完成后，会获得一个AccessToken，让您的用户把该AccessToken发给你。 AccessToken的有效期和您的用户购买Agiso软件的使用时间一致。如果您的用户续费，那么AccessToken的有效期也会延长。
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
把拼装好的字符串采用utf-8编码，在拼装的字符串前后加上app的secret后，使用MD5算法进行摘要，如：md5({$开发者应用的AppSecret}bar2foo1foo_bar3foobar4{$开发者应用的AppSecret})
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
      HttpPost httpPost = new HttpPost("https://gw-api.agiso.com/aldsPdd/Trade/LogisticsDummySend");
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

## 标签页：自动模式

1、接入流程

 


        拼接用户授权需访问url ，示例及参数说明如下：
        https://aldsPdd.agiso.com/#/authorize?appId={$开发者应用的AppId}&state={$开发者自定义参数}
        

 
参数名	必选	类型	说明
appId
	
是
	
long
	
应用的appId


state
	
否
	
string
	
开发者自定义参数，授权回调会把该参数回传回去
 

2、引导用户登录授权

 
          引导用户通过浏览器访问以上授权url
         

3、获取code

 
          用户点“授权”按钮后，Agiso自动发货会将授权码code、自定义参数state返回到了回调地址上，应用可以获取并使用该code去换取AccessToken
         

4、换取AccessToken

 
          通过访问 https://aldsPdd.agiso.com/auth/token?code={$实际获取到的code}&appId={$开发者应用的AppId}&sign={$md5后的签名}
          获取AccessToken换取AccessToken请求参数说明
         
参数名	必选	类型	说明
appId
	
是
	
long
	
应用的appId


code
	
是
	
string
	
上一步获取code得到


sign
	
是
	
string
	
跟接口的签名算法一致，md5({$开发者应用的AppSecret}appId{$开发者应用的AppId}code{$实际获取到的code}{$开发者应用的AppSecret})
 

换取AccessToken返回值示例

 
IsSuccess: true,
Error_Code: 0,
Error_Msg: "",
Data:{
    "FromPlatform":"PddAlds"
    "UserId":123456,
    "UserNick":"用户昵称",
    "ShopName":"卡券店铺",
    "ExpiresIn":165486,
    "Token":"alds_afoiqhwfaldhfoaseio",
    "SellerOpenUid ":"AAEF_gqxAAShiml5xxxxxxxx"
  }
 

换取AccessToken返回参数说明

 
参数名	类型	说明
FromPlatform
	
string
	
参数值：PddAlds。<a href="https://open.agiso.com/document/#/aldsPdd/faq" target="_blank">常见问题</a>


UserId
	
string
	
用户Id


UserNick
	
string
	
用户昵称


ShopId
	
string
	
店铺Id


ShopName
	
string
	
店铺名称


ExpiresIn
	
int
	
AccessToken过期时间（表示 n 秒后过期）


Token
	
string
	
AccessToken
