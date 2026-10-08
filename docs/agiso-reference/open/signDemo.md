# 签名算法

来源：https://open.agiso.com/document/#/open/signDemo（2026-10-08 抓取的渲染文本）

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

## 标签页：C#

var args = new Dictionary<string, string>()       
  {   
      {"modifyTimeStart","2016-07-13 10:44:30"},
      {"pageNo","1"},
      {"pageSize","20"},
      //timestamp 为调用Api的公共参数，详细说明参考接入指南
      {"timestamp",'1468476350'} //假设当前时间为2016/7/14 14:5:50
  };
  //排序
  var en = args.OrderBy(m => m.Key, StringComparer.Ordinal);
  string str = "";
  foreach (var m in en)
  {
      str += (m.Key + m.Value);
  }
  //到这str的值为modifyTimeStart2016-07-13 10:44:30pageNo1pageSize20timestamp1468476350
  //头尾加入AppSecret ，假设AppSecret值为******************
  str = ClientSecret + str + ClientSecret;  //str=******************modifyTimeStart2016-07-13 10:44:30pageNo1pageSize20timestamp1468476350******************
  var encodeStr = MD5Encrypt(str);   //encoderStr=935671331572EBF7F419EBB55EA28558
  //sign 为调用Api的公共参数，详细说明参考接入指南
  args.Add("sign", encodeStr);
  
  //Md5摘要
  public string MD5Encrypt(string text)
  {
      MD5 md5 = new MD5CryptoServiceProvider();
      byte[] fromData = System.Text.Encoding.UTF8.GetBytes(text);
      byte[] targetData = md5.ComputeHash(fromData);
      string byte2String = null;

      for (int i = 0; i < targetData.Length; i++)
      {
          byte2String += targetData[i].ToString("X2");
      }

      return byte2String;
  }

## 标签页：PHP

$params = array();
  $params['modifyTimeStart'] = '2016-07-13 10:44:30';
  $params['pageNo'] = '1';
  $params['pageSize'] = '20';
  //timestamp 为调用Api的公共参数，详细说明参考接入指南
  $params['timestamp'] = time();//假设当前时间为2016/7/14 14:5:50
  ksort($params);
  $str='';
  foreach ($args as $key => $value)
  {
      $str .= ($key . $value);
  }
  //到这$str的值为modifyTimeStart2016-07-13 10:44:30pageNo1pageSize20timestamp1468476350
  //头尾加入AppSecret ，假设AppSecret值为******************
  $str = $this->client_secret . $str . $this->client_secret; //$str=******************modifyTimeStart2016-07-13 10:44:30pageNo1pageSize20timestamp1468476350
  $encodeStr = md5($str); //$encodeStr=935671331572EBF7F419EBB55EA28558
  //sign 为调用Api的公共参数，详细说明参考接入指南
  $params['sign'] = $encodeStr;

## 标签页：Python

import hashlib
  from collections import OrderedDict
  
  def generate_sign(params, app_secret):
      # 1. 对参数键按字典序排序
      sorted_params = OrderedDict(sorted(params.items(), key=lambda x: x[0]))
  
      # 2. 拼接字符串：首尾加入 client_secret
      query_str = app_secret
      for key, value in sorted_params.items():
          query_str += f"{key}{value}"
      query_str += app_secret
  
      # 3. 计算 MD5 并转为小写十六进制
      md5 = hashlib.md5()
      md5.update(query_str.encode('utf-8'))
      sign = md5.hexdigest().lower()
      return sign
  
  # 示例使用
  if __name__ == "__main__":
      # 准备参数
      params = {
          "tids": "1234567789",
          "timestamp": "1468476350"  # 假设当前时间为 2016/7/14 14:5:50
      }
      app_secret = "******************"  # 替换为实际 AppSecret
  
      # 生成签名并添加到参数
      sign = generate_sign(params, app_secret)
      params["sign"] = sign
