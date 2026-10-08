# 查询商品列表

来源：https://open.agiso.com/document/#/aldsDoudian/api/productList（2026-10-08 抓取的渲染文本）

批量查询商品列表

简要描述：  接口调用示例

￥高级
批量查询商品列表

请求URL：

https://gw-api.agiso.com/aldsDoudian/Product/List

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
page
	
是
	
int
	
第几页（第一页为1，最大为100）


size
	
是
	
int
	
每页返回条数，最多支持100条


status
	
否
	
int?
	
指定状态返回商品列表：0上架 1下架


checkStatus
	
否
	
int?
	
指定审核状态返回商品列表：1未提审 2审核中 3审核通过 4审核驳回 5封禁 7审核通过，待上架状态

返回示例


    {
        "isSuccess": true,
        "data": {
            "data": [
                {
                    "product_id": 3693282087177158656,      // 商品ID 
                    "status": 0,                            // 商品上下架状态：0上架 1下架 
                    "check_status": 1,                      // 商品审核状态：1未提审 2审核中 3审核通过 4审核驳回 5封禁 
                    "market_price": 0,                      // 划线价，单位分 
                    "discount_price": 0,                    // 售价，单位分 
                    "img": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/SXJcUUhG_m_bdaff5747ab2c8a3bf81de7e2d9c5d81_sx_270988_www720-720",  // 商品图片url 
                    "name": "测试用商家编码勿拍",             // 商品名 
                    "pay_type": 1,                          // 支持的支付方式：0货到付款 1在线支付 2两者都支持 
                    "product_type": 0,                      // 0-普通，3-虚拟，6玉石闪购，7云闪购 
                    "spec_id": 1803361102927964,            // 规格id 
                    "cos_ratio": 0,                         // 佣金比例 
                    "create_time": 1719819168,              // 商品创建时间 
                    "update_time": 1719819169,              // 商品更新时间 
                    "out_product_id": 0,                    // 推荐使用，外部商家编码，支持字符串和数字2种 
                    "description": "",                      // 商品描述 
                    "mobile": "18065583339",                // 手机号 
                    "extra": "{"category_detail":{"enable":null,"first_cid":20048,"first_cname":"餐饮具","fourth_cid":0,"fourth_cname":"","is_leaf":true,"second_cid":20709,"second_cname":"餐具","third_cid":25363,"third_cname":"餐垫/隔热垫"},"is_publish":1,"quality_opId":"7386567066637189416","recruit_info":{"recruit_follow_id":"","recruit_follow_id_list":["27045807"],"recruit_source":"business_center","recruit_type":"3"},"spec_seq_info":{"child_spec_seq":["默认"],"spec_values_seq":[["默认"]]}}",    // 额外信息，如资质 
                    "recommend_remark": "",                 // 商家推荐语 
                    "category_detail": {
                        "first_cid": 20048,                 // 一级类目 
                        "second_cid": 20709,                // 二级类目 
                        "third_cid": 25363,                 // 三级类目 
                        "fourth_cid": 0,                    // 四级类目 
                        "first_cname": "餐饮具",            // 一级类目名称 
                        "second_cname": "餐具",             // 二级类目名称 
                        "third_cname": "餐垫/隔热垫",       // 三级类目名称 
                        "fourth_cname": ""                  // 四级类目名称 
                    },
                    "outer_product_id": "",                 // 推荐使用，外部商家编码，支持字符串和数字2种 
                    "is_package_product": false             // 是否是组套商品 
                },
                {
                    "product_id": 3660207428038974464,
                    "status": 0,
                    "check_status": 3,
                    "market_price": 1,
                    "discount_price": 1,
                    "img": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/SXJcUUhG_m_0b9d7c9892e9b1c905015b4ef1f32a07_sx_309394_www1500-1500",
                    "name": "办公椅，测试商品，勿拍",
                    "pay_type": 1,
                    "product_type": 0,
                    "spec_id": 1805244445943844,
                    "cos_ratio": 0,
                    "create_time": 1704416903,
                    "update_time": 1722233275,
                    "out_product_id": 0,
                    "description": "",
                    "mobile": "18065583339",
                    "extra": "{"category_detail":{"first_cid":20036,"first_cname":"商业/办公家具","fourth_cid":0,"fourth_cname":"","is_leaf":true,"second_cid":20658,"second_cname":"办公家具","third_cid":24998,"third_cname":"办公椅"},"is_publish":1,"quality_opId":"7394281245661921575","spec_seq_info":{"child_spec_seq":["颜色"],"spec_values_seq":[["白色","黑色"]]}}",
                    "recommend_remark": "",
                    "category_detail": {
                        "first_cid": 20036,
                        "second_cid": 20658,
                        "third_cid": 24998,
                        "fourth_cid": 0,
                        "first_cname": "商业/办公家具",
                        "second_cname": "办公家具",
                        "third_cname": "办公椅",
                        "fourth_cname": ""
                    },
                    "outer_product_id": "",
                    "is_package_product": false
                }
            ],
            "total": 4,     // 总数 
            "page": 1,      // 当前分页 
            "size": 2       // 每页数量 
        },
        "error_Code": 0,
        "error_Msg": ""
    }
