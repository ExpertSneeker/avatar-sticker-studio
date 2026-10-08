# 商品列表

来源：https://open.agiso.com/document/#/aldsPdd/api/goodsList（2026-10-08 抓取的渲染文本）

商品列表

简要描述：  接口调用示例

￥高级
商品列表查询

请求URL：

https://gw-api.agiso.com/aldsPdd/Goods/List

请求方式：

POST

公共Header：

参数名	必选	类型	说明
Authorization
	
是
	
string
	
httpPost.addHeader("Authorization","Bearer "+ accessToken)


ApiVersion
	
是
	
string
	
httpPost.addHeader("ApiVersion", "1")


Content-Type
	
是
	
string
	
值必须为：application/x-www-form-urlencoded

公共参数：

参数名	必选	类型	说明
timestamp
	
是
	
Date
	
时间戳，例如：1468476350。API服务端允许客户端请求最大时间误差为10分钟。


sign
	
是
	
string
	
API输入参数签名结果,签名算法参照下面的介绍。

参数：

参数名	必选	类型	说明
outerId
	
否
	
String
	
商品外部编码（sku）


goodsName
	
否
	
String
	
商品名称


isOnsale
	
否
	
Number
	
上下架状态，0-下架，1-上架


page
	
否
	
Number
	
页码默认 1


pageSize
	
否
	
Number
	
默认100，最大100

返回示例


    {
      "IsSuccess": true,
      "Data": {
        "total_count": 10,  // 商品总数
        "goods_list:[  // 商品列表
          {
            "thumb_url":"https://xx.xx.com/xxx.jpg",  // 商品缩略图
            "goods_id": 1000,  // 商品Id
            "goods_name": "商品名称",  // 商品名称
            "image_url": "商品图片",  // 商品图片
            "is_more_sku": 0,  // 是否多sku，0-单sku，1-多sku
            "goods_quantity": 58,  // 商品总数量
            "is_onsale": 1,  // 是否在架上，0-下架中，1-架上
            "sku_list": [
              "spec": "规格名称",  // 规格名称
              "sku_id": 3163516514,  // sku Id
              "sku_quantity": 1000,  // sku库存
              "outer_id": "商家外部编码（sku）",  // 商家外部编码（sku）
              "outer_goods_id": "商家外部编码（商品）",  // 商家外部编码（商品）
              "is_sku_onsale": 1,  // sku是否在架上，0-下架中，1-架上
              "reserve_quantity": 0  // sku预扣库存
            ],
            "goods_reserve_quantity": 0  // 商品预扣库存
          }
        ]
      }
      "Error_Code": 0,
      "Error_Msg": ""
      "AllowRetry": null,
      "RequestId": "20201027142251106"
    }
